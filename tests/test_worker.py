"""模型加载/推理的工作线程。

之前零测试。核心风险是**加载失败时把本来能用的引擎弄丢**:
原来第一行就是 `self._engine = None`,于是配置填错(模型目录敲错一个字母)
会从"改错一个设置"升级成"整个程序不能用",而用户只是想调个线程数。
"""

from unittest.mock import patch

import numpy as np
import pytest

from voiceinput.asr.base import EngineError, Transcription
from voiceinput.config import Config
from voiceinput.worker import EngineWorker


class FakeEngine:
    def __init__(self, name="fake", text="识别结果", fail_transcribe=False) -> None:
        self.name = name
        self._text = text
        self._fail = fail_transcribe
        self.loaded = False
        self.unloaded = False

    @property
    def is_loaded(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.unloaded = True
        self.loaded = False

    def transcribe(self, audio, sample_rate) -> Transcription:
        if self._fail:
            raise EngineError("推理炸了")
        return Transcription(self._text, 0.1, 1.0)


@pytest.fixture
def worker():
    w = EngineWorker()
    w.events: dict = {"loaded": [], "loadFailed": [], "ok": [], "fail": []}
    w.loaded.connect(w.events["loaded"].append)
    w.loadFailed.connect(lambda m, ok: w.events["loadFailed"].append((m, ok)))
    w.transcribed.connect(lambda r, a: w.events["ok"].append((r.text, a)))
    w.transcribeFailed.connect(lambda m, a: w.events["fail"].append((m, a)))
    return w


def load_with(worker, engine_or_error) -> None:
    kw = ({"side_effect": engine_or_error}
          if isinstance(engine_or_error, Exception)
          else {"return_value": engine_or_error})
    with patch("voiceinput.asr.build_engine", **kw):
        worker.load(Config())


class TestLoad:
    def test_success(self, worker):
        engine = FakeEngine()
        load_with(worker, engine)
        assert engine.loaded
        assert len(worker.events["loaded"]) == 1

    def test_engine_error_reported(self, worker):
        load_with(worker, EngineError("模型文件缺失"))
        assert worker.events["loadFailed"] == [("模型文件缺失", False)]

    def test_unexpected_error_also_reported(self, worker):
        """引擎实现里漏掉的异常不能让工作线程静默死掉。"""
        load_with(worker, ValueError("没想到吧"))
        assert len(worker.events["loadFailed"]) == 1
        assert "没想到吧" in worker.events["loadFailed"][0][0]


class TestKeepsWorkingEngineOnFailure:
    """**新的加载成功之前绝不动旧的。**"""

    def test_old_engine_survives_failed_reload(self, worker):
        good = FakeEngine("好的")
        load_with(worker, good)
        load_with(worker, EngineError("路径敲错了"))
        assert worker._engine is good, "失败的重载不该弄丢能用的引擎"

    def test_still_transcribes_after_failed_reload(self, worker):
        """这才是用户真正关心的:改错设置之后热键还能不能用。"""
        load_with(worker, FakeEngine(text="还能用"))
        load_with(worker, EngineError("路径敲错了"))
        worker.transcribe(np.zeros(16000, dtype=np.float32), 16000, "paste")
        assert worker.events["ok"] == [("还能用", "paste")]

    def test_failure_reports_engine_still_usable(self, worker):
        """上层要靠这个标志决定禁不禁热键。旧引擎还在就不该禁。"""
        load_with(worker, FakeEngine())
        load_with(worker, EngineError("失败"))
        assert worker.events["loadFailed"][-1][1] is True

    def test_first_load_failure_reports_unusable(self):
        """首次加载就失败 —— 确实没有可用引擎。"""
        w = EngineWorker()
        got = []
        w.loadFailed.connect(lambda m, ok: got.append(ok))
        with patch("voiceinput.asr.build_engine", side_effect=EngineError("x")):
            w.load(Config())
        assert got == [False]

    def test_old_engine_not_unloaded_on_failure(self, worker):
        good = FakeEngine()
        load_with(worker, good)
        load_with(worker, EngineError("失败"))
        assert not good.unloaded

    def test_old_engine_unloaded_after_successful_swap(self, worker):
        """换成功了才放掉旧的,否则内存里会一直留着两份。"""
        old, new = FakeEngine("旧"), FakeEngine("新")
        load_with(worker, old)
        load_with(worker, new)
        assert old.unloaded
        assert worker._engine is new

    def test_unload_failure_does_not_fail_the_load(self, worker):
        class Stubborn(FakeEngine):
            def unload(self):
                raise RuntimeError("放不掉")

        load_with(worker, Stubborn())
        load_with(worker, FakeEngine("新"))
        assert len(worker.events["loaded"]) == 2
        assert worker.events["loadFailed"] == []


class TestTranscribe:
    def test_before_load(self, worker):
        worker.transcribe(np.zeros(16000, dtype=np.float32), 16000, "paste")
        assert worker.events["fail"] == [("模型尚未加载完成", "paste")]

    def test_success_carries_action_through(self, worker):
        """action 要原样带回去 —— 它决定粘贴后要不要补回车。"""
        load_with(worker, FakeEngine(text="你好"))
        worker.transcribe(np.zeros(16000, dtype=np.float32), 16000, "paste_and_send")
        assert worker.events["ok"] == [("你好", "paste_and_send")]

    def test_engine_error_carries_action(self, worker):
        load_with(worker, FakeEngine(fail_transcribe=True))
        worker.transcribe(np.zeros(16000, dtype=np.float32), 16000, "wizard")
        assert worker.events["fail"] == [("推理炸了", "wizard")]

    def test_unexpected_error_carries_action(self, worker):
        class Exploding(FakeEngine):
            def transcribe(self, audio, sample_rate):
                raise ValueError("意外")

        load_with(worker, Exploding())
        worker.transcribe(np.zeros(16000, dtype=np.float32), 16000, "paste")
        assert len(worker.events["fail"]) == 1
        assert worker.events["fail"][0][1] == "paste"


class TestUnload:
    def test_clears_engine(self, worker):
        engine = FakeEngine()
        load_with(worker, engine)
        worker.unload()
        assert worker._engine is None
        assert engine.unloaded

    def test_unload_without_engine_is_safe(self, worker):
        worker.unload()
        assert worker._engine is None
