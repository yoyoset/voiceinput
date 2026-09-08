"""App → worker 的跨线程派发。

**这条路径曾经完全是坏的,而且没有任何检查会发现。**

原来用 `QMetaObject.invokeMethod(worker, "load", Q_ARG(object, cfg))`。
PySide6 里这样传 Python 对象直接抛:

    RuntimeError: qArgDataFromPyType: Unable to find a QMetaType for "object"

而它跑在 `QTimer` 回调里,异常被 Qt 打到 stderr 之后吞掉 ——
windowed 打包后连 stderr 都没有,于是**完全静默**:
程序从来没加载过模型,界面上只显示"正在加载模型…",日志里一行错误都没有。

自检九项全过,因为**自检是直接调引擎的,从没走过这条派发路径**。
这组测试就是补上那个盲区。
"""

import numpy as np
import pytest

from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Signal

from voiceinput.asr.base import Transcription
from voiceinput.config import Config
from voiceinput.worker import EngineWorker


class Driver(QObject):
    """模拟 App 上那两个信号。"""

    loadRequested = Signal(object)
    transcribeRequested = Signal(object, int, str)


class FakeEngine:
    def __init__(self) -> None:
        self.loaded = False

    @property
    def is_loaded(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def transcribe(self, audio, sample_rate) -> Transcription:
        # 把收到的采样率带回去,好断言它没被改过
        return Transcription(f"sr={sample_rate}", 0.1, 1.0)


@pytest.fixture
def rig(qapp, monkeypatch):
    """worker 跑在**真的另一个线程**上 —— 同线程测不出跨线程编组的问题。"""
    monkeypatch.setattr("voiceinput.asr.build_engine", lambda cfg: FakeEngine())
    thread = QThread()
    worker = EngineWorker()
    worker.moveToThread(thread)
    driver = Driver()
    driver.loadRequested.connect(worker.load)
    driver.transcribeRequested.connect(worker.transcribe)
    thread.start()
    yield driver, worker
    thread.quit()
    thread.wait(3000)


def watch(signal) -> list:
    """开始收集这个信号的参数。**必须在 emit 之前调用。**

    原来是 `wait_for(signal)` 一把梭:先 emit,再连信号进事件循环等。
    worker 在另一个真线程上,FakeEngine 又是瞬间返回的 —— 它完全可能
    **在主线程连上信号之前就已经发完了**,于是等到超时,测试随机变红。

    随机变红的测试比没有测试更坏:它教人"再跑一遍就好了"。
    所以顺序反过来 —— 先架好收集器,再触发。
    """
    got: list = []
    signal.connect(lambda *a: got.extend(a))
    return got


def wait_for(got: list, timeout_ms: int = 5000) -> list:
    """等 `watch()` 收到东西。超时返回空 —— 空列表 = 信号根本没送到。"""
    if got:
        return got                      # 已经到了,不用进事件循环
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    poll.timeout.connect(lambda: got and loop.quit())
    poll.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    poll.stop()
    return got


class TestLoadDispatch:
    def test_load_actually_reaches_worker(self, rig):
        """核心断言:信号真的跨线程送到了 worker 并执行了。

        之前这里是静默失败的 —— 什么都不会发生,也没有任何报错。
        """
        driver, worker = rig
        loaded = watch(worker.loaded)
        driver.loadRequested.emit(Config())
        assert wait_for(loaded), "load 信号没送到 worker"

    def test_config_survives_the_crossing(self, rig):
        """Python 对象要能完整穿过线程边界 —— Q_ARG 正是栽在这里。"""
        driver, worker = rig
        cfg = Config()
        cfg.engine.num_threads = 12
        loaded = watch(worker.loaded)
        driver.loadRequested.emit(cfg)
        assert wait_for(loaded)
        assert worker._engine is not None


class TestTranscribeDispatch:
    def test_transcribe_reaches_worker(self, rig):
        driver, worker = rig
        loaded = watch(worker.loaded)
        driver.loadRequested.emit(Config())
        assert wait_for(loaded)

        done = watch(worker.transcribed)
        driver.transcribeRequested.emit(np.zeros(16000, dtype=np.float32), 16000, "paste")
        got = wait_for(done)
        assert got, "transcribe 信号没送到 worker"

    def test_numpy_array_survives_the_crossing(self, rig):
        """音频是 numpy 数组,也是个 Python 对象,同样要能穿过去。"""
        driver, worker = rig
        loaded = watch(worker.loaded)
        driver.loadRequested.emit(Config())
        assert wait_for(loaded)

        done = watch(worker.transcribed)
        driver.transcribeRequested.emit(np.zeros(16000, dtype=np.float32), 48000, "paste")
        got = wait_for(done)
        assert got and got[0].text == "sr=48000", "采样率没原样传过去"

    def test_action_survives_the_crossing(self, rig):
        """action 决定粘贴后要不要补回车,传丢了行为就错了。"""
        driver, worker = rig
        loaded = watch(worker.loaded)
        driver.loadRequested.emit(Config())
        assert wait_for(loaded)

        done = watch(worker.transcribed)
        driver.transcribeRequested.emit(
            np.zeros(16000, dtype=np.float32), 16000, "paste_and_send")
        got = wait_for(done)
        assert got and got[1] == "paste_and_send"


class TestQArgIsUnusable:
    def test_q_arg_with_object_raises(self, qapp):
        """把根因钉住,免得以后有人"优化"回 invokeMethod。

        PySide6 没有 `object` 的 QMetaType,`Q_ARG(object, ...)` 直接抛。
        """
        from PySide6.QtCore import Q_ARG

        with pytest.raises(RuntimeError, match="QMetaType"):
            Q_ARG(object, Config())
