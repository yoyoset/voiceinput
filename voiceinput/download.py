"""模型下载与解压。

向导里要能一键装好模型,不能只弹个框叫用户自己去敲 curl。

刻意只提供**一个**模型选项:2024-07-17 原版 SenseVoice。
同一个 release 页上的 2025-09-09 是粤语特化微调,中英日韩全线崩坏
(详见 docs/engine-benchmark.md),把它摆进选项里只会让人选错。
"""

from __future__ import annotations

import http.client
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{MODEL_NAME}.tar.bz2"
)
APPROX_BYTES = 164_000_000  # 服务器不一定给 Content-Length,拿它兜底算百分比
MAX_ATTEMPTS = 3
RETRY_DELAY_S = 3
SOCKET_TIMEOUT = 30


class IncompleteDownload(Exception):
    """收到的字节数比服务器声明的少 —— 连接被中途掐断了。

    单独立一个类型是因为它**不是**异常抛出来的:read() 可能干净地返回 EOF,
    只能靠核对字节数发现。要走和网络错误一样的重试路径。
    """


def _total_bytes(resp, already: int) -> int:
    """从响应头推算文件总大小。

    续传时 Content-Length 只是**剩余**长度,直接拿来算百分比会让进度条乱跳,
    所以要把已下载的部分加回去。
    """
    length = int(resp.headers.get("Content-Length") or 0)
    if not length:
        return APPROX_BYTES
    return length + already if resp.status == 206 else length


def _reason(e: Exception) -> str:
    reason = getattr(e, "reason", None)
    return str(reason) if reason is not None else str(e)


@dataclass
class ModelStatus:
    present: bool
    message: str
    path: Path
    warning: str = ""
    """模型能用,但不是推荐的那个。空串表示没问题。"""


# 模型出处的标记字符串。实测就落在文件**最后 4KB** 的元数据里,
# 所以只读尾部就够,不用扫两百多 MB。
_TAIL_BYTES = 8192
_WRONG_VARIANT_MARKERS = (b"WSYue", b"ASLP-lab", b"sensevoice_small_yue")
_EXPECTED_MARKER = b"FunAudioLLM"

WRONG_VARIANT_WARNING = (
    "这是**粤语特化微调版**(ASLP-lab/WSYue-ASR),不是通用原版。"
    "实测中文会吞字、英文拼错、日韩基本不可用,而且丢失标点。"
    "请换成 2024-07-17 原版。"
)


def identify(model_file: Path) -> str:
    """认一下这个模型文件是哪一版。返回 "" 表示认不出(可能是将来的新模型)。

    **为什么需要这个**:整个项目最强调的坑就是"别用 2025-09-09 粤语版",
    而两个模型都是两百多 MB、文件名可以随便改 —— 只看大小完全分不出。
    放错了不会报错,只是识别悄悄变差,用户根本不知道该怀疑模型。
    """
    try:
        size = model_file.stat().st_size
        with model_file.open("rb") as f:
            f.seek(max(0, size - _TAIL_BYTES))
            tail = f.read()
    except OSError:
        return ""
    if any(m in tail for m in _WRONG_VARIANT_MARKERS):
        return "yue"
    if _EXPECTED_MARKER in tail:
        return "original"
    return ""


def check(model_dir: Path) -> ModelStatus:
    """模型在不在、像不像话、是不是那一版。

    只看文件存不存在是不够的:下载中断留下的半个文件也"存在"。
    模型本体两百多 MB,小于 100MB 一定不完整。
    大小对了也还不够 —— 粤语版同样是两百多 MB,见 identify()。
    """
    model = model_dir / "model.int8.onnx"
    tokens = model_dir / "tokens.txt"

    if not model_dir.is_dir():
        return ModelStatus(False, "模型目录不存在", model_dir)
    missing = [p.name for p in (model, tokens) if not p.exists()]
    if missing:
        return ModelStatus(False, f"缺少文件:{', '.join(missing)}", model_dir)

    size_mb = model.stat().st_size / 1024 / 1024
    if size_mb < 100:
        return ModelStatus(
            False, f"模型文件只有 {size_mb:.0f} MB,像是没下完", model_dir
        )

    warning = WRONG_VARIANT_WARNING if identify(model) == "yue" else ""
    return ModelStatus(True, f"已就绪({size_mb:.0f} MB)", model_dir, warning)


class DownloadWorker(QObject):
    """在工作线程里下载并解压。

    进度分两段:下载 0–90%,解压 90–100%。解压两百多 MB 也要几秒,
    进度条卡在 100% 不动会让人以为死了。
    """

    progress = Signal(int, str)   # 百分比, 说明
    finished = Signal(str)        # 解压后的模型目录
    failed = Signal(str)

    def __init__(self, target_root: Path) -> None:
        super().__init__()
        self._target_root = Path(target_root)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit(0, "正在连接…")
            self._target_root.mkdir(parents=True, exist_ok=True)
            # **不放临时目录**:放这里才能跨次点击续传。
            # 用临时目录的话 finally 一删,"已下载的部分会保留"就成了假话。
            archive = self._target_root / f"{MODEL_NAME}.tar.bz2.part"

            if not self._download(archive):
                return  # 已经 emit 过 failed 或取消,.part 留着下次续

            self.progress.emit(90, "正在解压…")
            with tarfile.open(archive, "r:bz2") as tar:
                # 防目录穿越:压缩包里的路径不能跑到目标目录外面去
                members = [m for m in tar.getmembers() if self._safe_member(m)]
                tar.extractall(self._target_root, members=members, filter="data")

            result = self._target_root / MODEL_NAME
            if not (result / "model.int8.onnx").exists():
                self.failed.emit(f"解压后没找到模型文件:{result}")
                return

            archive.unlink(missing_ok=True)   # 成功了才删,失败时留着续传

            # 模型自带的示例音频对使用没用,占几 MB
            shutil.rmtree(result / "test_wavs", ignore_errors=True)

            self.progress.emit(100, "完成")
            self.finished.emit(str(result))
        except tarfile.TarError as e:
            # 包本身是坏的(多半是续传接在了残缺文件后面)。必须删掉,
            # 否则下次续传会一直往坏文件后面追加,永远好不了。
            archive.unlink(missing_ok=True)
            self.failed.emit(f"压缩包损坏,已清理,请重新下载:{e}")
        except Exception as e:
            self.failed.emit(f"下载失败:{e}")

    @staticmethod
    def _safe_member(member: tarfile.TarInfo) -> bool:
        name = member.name.replace("\\", "/")
        return not (name.startswith("/") or ".." in name.split("/"))

    def _download(self, target: Path) -> bool:
        """带重试和断点续传地下载。

        155MB 的传输遇到一次网络抖动就整个失败、还要从 0% 重来,是不能接受的。
        实测过:同一台机器同一个源,第一次 21 秒后 WinError 10060,
        第二次完整跑通 —— 偶发抖动就是常态。

        续传靠 HTTP Range:重试时带上已下到的字节数。服务器回 206 就接着写,
        回 200 说明它不支持 Range(或文件变了),那就老老实实从头来。
        """
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._cancelled:
                self.failed.emit("已取消")
                return False

            got = target.stat().st_size if target.exists() else 0
            headers = {"User-Agent": "voiceinput"}
            if got:
                headers["Range"] = f"bytes={got}-"

            try:
                req = urllib.request.Request(MODEL_URL, headers=headers)
                with urllib.request.urlopen(req, timeout=SOCKET_TIMEOUT) as resp:
                    resuming = resp.status == 206
                    if got and not resuming:
                        got = 0          # 服务器不支持续传,从头来
                    total = _total_bytes(resp, got)
                    known = bool(resp.headers.get("Content-Length"))

                    mode = "ab" if resuming else "wb"
                    with target.open(mode) as f:
                        while True:
                            if self._cancelled:
                                self.failed.emit("已取消")
                                return False
                            chunk = resp.read(1 << 18)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            self.progress.emit(
                                min(89, int(got * 90 / max(total, 1))),
                                f"下载中 {got / 1048576:.0f} / {total / 1048576:.0f} MB"
                                + (f"(第 {attempt} 次尝试)" if attempt > 1 else ""),
                            )

                # **必须核对字节数**,不能只看循环有没有正常结束。
                # 连接被中途掐断时 read() 可能干净地返回 EOF,循环就这么退出了 ——
                # 于是截断的下载被当成成功,一直到解压才报"not a bzip2 file"。
                # (这个 bug 是本项目自己写出来又被测试抓到的。)
                if known and got < total:
                    raise IncompleteDownload(
                        f"只收到 {got}/{total} 字节,连接被中断")
                return True

            except (urllib.error.URLError, OSError, http.client.HTTPException,
                    IncompleteDownload) as e:
                last_error = _reason(e)
                if attempt < MAX_ATTEMPTS:
                    self.progress.emit(
                        min(89, int(got * 90 / APPROX_BYTES)),
                        f"网络中断,{RETRY_DELAY_S} 秒后重试({attempt}/{MAX_ATTEMPTS})…",
                    )
                    time.sleep(RETRY_DELAY_S)

        self.failed.emit(
            f"下载失败({MAX_ATTEMPTS} 次尝试):{last_error}\n"
            "可以再点一次继续(已下载的部分会保留),"
            "或者按 README 里的命令手动下载模型。"
        )
        return False
