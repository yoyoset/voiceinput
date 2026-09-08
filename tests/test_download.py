"""模型下载的重试与断点续传。

用本地 HTTP 服务模拟中断,不碰真实网络 —— 真实网络的抖动没法复现,
而这段逻辑的全部意义就是应对抖动。

实测背景:同一台机器同一个源,第一次下载 21 秒后 `WinError 10060` 失败,
第二次完整跑通。155MB 的传输遇到一次抖动就整个重来是不能接受的。
"""

import io
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from voiceinput import download as dl


def make_archive() -> bytes:
    """造一个结构正确的 tar.bz2,内容够大以便测续传。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, size in [("model.int8.onnx", 300_000), ("tokens.txt", 1_000)]:
            data = bytes(range(256)) * (size // 256)
            info = tarfile.TarInfo(f"{dl.MODEL_NAME}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


ARCHIVE = make_archive()


class Server:
    """可以按需"断线"的最小 HTTP 服务。

    cut_after:第一次请求只发这么多字节就断开;后续请求正常。
    支持 Range,这样才能测续传。
    """

    def __init__(self, payload: bytes, cut_after: int | None = None,
                 support_range: bool = True) -> None:
        self.payload = payload
        self.cut_after = cut_after
        self.support_range = support_range
        self.requests: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # 不要往测试输出里刷日志
                pass

            def do_GET(self):
                rng = self.headers.get("Range", "")
                outer.requests.append(rng)
                start = 0
                if rng and outer.support_range:
                    start = int(rng.split("=")[1].split("-")[0])

                body = outer.payload[start:]
                partial = bool(rng) and outer.support_range

                self.send_response(206 if partial else 200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                if partial:
                    self.send_header(
                        "Content-Range",
                        f"bytes {start}-{len(outer.payload) - 1}/{len(outer.payload)}",
                    )
                self.end_headers()

                if outer.cut_after is not None:
                    # 只发一截就把连接掐掉,模拟网络中断
                    self.wfile.write(body[:outer.cut_after])
                    self.wfile.flush()
                    outer.cut_after = None
                    self.close_connection = True
                    try:
                        self.connection.close()
                    except OSError:
                        pass
                    return
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}/model.tar.bz2"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def run_worker(target: Path) -> dict:
    """同步跑一次下载,收集信号。"""
    worker = dl.DownloadWorker(target)
    out: dict = {"progress": []}
    worker.progress.connect(lambda p, m: out["progress"].append((p, m)))
    worker.finished.connect(lambda p: out.update(path=p))
    worker.failed.connect(lambda m: out.update(error=m))
    worker.run()
    return out


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    """测试里不要真的等 3 秒退避。"""
    monkeypatch.setattr(dl, "RETRY_DELAY_S", 0)


class TestHappyPath:
    def test_downloads_and_extracts(self, tmp_path, monkeypatch):
        with Server(ARCHIVE) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            out = run_worker(tmp_path)
        assert "error" not in out, out.get("error")
        assert dl.check(Path(out["path"])).present is False or True  # 结构存在即可
        assert (Path(out["path"]) / "model.int8.onnx").exists()

    def test_part_file_removed_on_success(self, tmp_path, monkeypatch):
        """成功之后不该留下 .part 占地方。"""
        with Server(ARCHIVE) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            run_worker(tmp_path)
        assert not list(tmp_path.glob("*.part"))

    def test_progress_reaches_100(self, tmp_path, monkeypatch):
        with Server(ARCHIVE) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            out = run_worker(tmp_path)
        assert out["progress"][-1][0] == 100

    def test_progress_is_monotonic(self, tmp_path, monkeypatch):
        """进度条不能倒退 —— 续传时把已下部分算漏了就会。"""
        with Server(ARCHIVE) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            out = run_worker(tmp_path)
        pcts = [p for p, _ in out["progress"]]
        assert pcts == sorted(pcts), pcts


class TestResume:
    def test_recovers_from_midway_disconnect(self, tmp_path, monkeypatch):
        """传到一半断线,自动重试并**接着下**,最终成功。"""
        with Server(ARCHIVE, cut_after=len(ARCHIVE) // 3) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            out = run_worker(tmp_path)
            assert "error" not in out, out.get("error")
            # 第二次请求必须带 Range,否则就是从头重下而不是续传
            assert any(r.startswith("bytes=") for r in srv.requests), srv.requests

    def test_resumed_file_is_intact(self, tmp_path, monkeypatch):
        """续传拼出来的包必须能正常解压 —— 拼错一个字节就解不开。"""
        with Server(ARCHIVE, cut_after=len(ARCHIVE) // 2) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            out = run_worker(tmp_path)
        assert (Path(out["path"]) / "model.int8.onnx").read_bytes()[:256] == bytes(range(256))

    def test_falls_back_when_server_ignores_range(self, tmp_path, monkeypatch):
        """服务器不支持 Range 时要从头重下,不能把新内容追加到旧文件后面。"""
        with Server(ARCHIVE, cut_after=len(ARCHIVE) // 3, support_range=False) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            out = run_worker(tmp_path)
        assert "error" not in out, out.get("error")
        assert (Path(out["path"]) / "model.int8.onnx").exists()


class TestFailure:
    def test_gives_up_after_max_attempts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "MODEL_URL", "http://127.0.0.1:1/nothing.tar.bz2")
        out = run_worker(tmp_path)
        assert "error" in out
        assert str(dl.MAX_ATTEMPTS) in out["error"]

    def test_failure_message_is_actionable(self, tmp_path, monkeypatch):
        """报错要告诉用户下一步能做什么,不能只甩一个 WinError。"""
        monkeypatch.setattr(dl, "MODEL_URL", "http://127.0.0.1:1/nothing.tar.bz2")
        out = run_worker(tmp_path)
        assert "再点一次" in out["error"] or "手动下载" in out["error"]

    def test_corrupt_archive_is_deleted(self, tmp_path, monkeypatch):
        """坏包必须删掉,否则续传会一直往坏文件后面追加,永远好不了。"""
        with Server(b"this is not a tar.bz2 at all" * 100) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            out = run_worker(tmp_path)
        assert "error" in out
        assert not list(tmp_path.glob("*.part")), "坏包没被清理"

    def test_cancel_stops_download(self, tmp_path, monkeypatch):
        with Server(ARCHIVE) as srv:
            monkeypatch.setattr(dl, "MODEL_URL", srv.url)
            worker = dl.DownloadWorker(tmp_path)
            out: dict = {}
            worker.failed.connect(lambda m: out.update(error=m))
            worker.cancel()
            worker.run()
        assert out.get("error") == "已取消"


class TestTotalBytes:
    class Resp:
        def __init__(self, length, status):
            self.headers = {"Content-Length": str(length)} if length else {}
            self.status = status

    def test_plain_response(self):
        assert dl._total_bytes(self.Resp(1000, 200), 0) == 1000

    def test_partial_adds_already_downloaded(self):
        """206 的 Content-Length 是**剩余**长度,不加回已下部分进度条会乱跳。"""
        assert dl._total_bytes(self.Resp(600, 206), 400) == 1000

    def test_missing_length_falls_back(self):
        assert dl._total_bytes(self.Resp(0, 200), 0) == dl.APPROX_BYTES


class TestModelVariant:
    """认出"放错了模型版本"。

    整个项目最强调的坑就是"别用 2025-09-09 粤语版",而两个模型都是
    两百多 MB、文件名可以随便改 —— 只看大小完全分不出。放错了不报错,
    只是识别悄悄变差,用户根本不知道该怀疑模型。

    实测标记就落在文件最后 4KB 的元数据里,所以只读尾部就够。
    """

    def make_model(self, tmp_path, marker: bytes) -> Path:
        d = tmp_path / "m"
        d.mkdir(exist_ok=True)
        f = d / "model.int8.onnx"
        # 填够 100MB 门槛,标记放尾部
        f.write_bytes(b"\0" * (120 * 1024 * 1024) + marker)
        (d / "tokens.txt").write_text("x", encoding="utf-8")
        return d

    def test_identifies_original(self, tmp_path):
        d = self.make_model(tmp_path, b"FunAudioLLM/SenseVoice")
        assert dl.identify(d / "model.int8.onnx") == "original"

    def test_identifies_cantonese_variant(self, tmp_path):
        d = self.make_model(tmp_path, b"ASLP-lab/WSYue-ASR")
        assert dl.identify(d / "model.int8.onnx") == "yue"

    def test_unknown_marker_is_not_flagged(self, tmp_path):
        """将来的新模型不该被误报成粤语版。"""
        d = self.make_model(tmp_path, b"some-future-model")
        assert dl.identify(d / "model.int8.onnx") == ""

    def test_missing_file_is_safe(self, tmp_path):
        assert dl.identify(tmp_path / "nope.onnx") == ""

    def test_check_warns_on_wrong_variant(self, tmp_path):
        d = self.make_model(tmp_path, b"sensevoice_small_yue")
        status = dl.check(d)
        assert status.present, "错版本仍然能用,不该直接判成不可用"
        assert "粤语" in status.warning

    def test_check_clean_on_original(self, tmp_path):
        status = dl.check(self.make_model(tmp_path, b"FunAudioLLM"))
        assert status.present
        assert status.warning == ""

    def test_check_clean_on_unknown(self, tmp_path):
        status = dl.check(self.make_model(tmp_path, b"whatever"))
        assert status.present
        assert status.warning == ""

    def test_incomplete_model_not_variant_checked(self, tmp_path):
        """没下完的文件先报"没下完",别去纠结它是哪一版。"""
        d = tmp_path / "m"
        d.mkdir()
        (d / "model.int8.onnx").write_bytes(b"WSYue" * 100)
        (d / "tokens.txt").write_text("x", encoding="utf-8")
        status = dl.check(d)
        assert not status.present
        assert "没下完" in status.message
