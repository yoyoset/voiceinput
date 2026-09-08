"""录音会话的状态机。

以前这五样状态(Recorder、忙碌标记、看门狗、电平定时器、削音警告)
散在 App 里,被七八个方法各自读写 —— 想单独测就得构造完整的 App,
而那会起托盘、抢全局热键。抽成 RecordingSession 之后,
**整条状态机不认识任何界面**,可以直接测。

其中最要命的一条:`is_busy` 卡住会让热键彻底静默失效 ——
按了什么都不发生,也没有任何提示。
"""

import numpy as np
import pytest

from voiceinput.audio import RecordingError
from voiceinput.session import TRANSCRIBE_TIMEOUT_MS, RecordingSession


class FakeRecorder:
    """替身录音机。默认返回一段听得见的噪声。"""

    def __init__(self, audio=None, truncated=False, overflowed=False,
                 max_seconds=120.0, sample_rate=48000):
        rng = np.random.default_rng(0)
        self._audio = rng.normal(0, 0.2, 16000).astype(np.float32) \
            if audio is None else audio
        self.truncated = truncated
        self.overflowed = overflowed
        self.max_seconds = max_seconds
        self.sample_rate = sample_rate
        self.duration_seconds = 1.0
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        return self._audio

    def peek_level(self):
        return -20.0


@pytest.fixture
def session(qapp):
    s = RecordingSession()
    yield s
    s.abort()


def install(monkeypatch, recorder):
    monkeypatch.setattr("voiceinput.session.Recorder", lambda **kw: recorder)


class TestBegin:
    def test_starts_and_announces(self, session, monkeypatch):
        rec = FakeRecorder()
        install(monkeypatch, rec)
        seen = []
        session.started.connect(seen.append)

        assert session.begin("paste", None, 120.0) is True
        assert rec.started and session.is_recording
        assert seen == ["paste"]

    def test_second_begin_is_ignored(self, session, monkeypatch):
        install(monkeypatch, FakeRecorder())
        session.begin("paste", None, 120.0)
        assert session.begin("paste", None, 120.0) is False

    def test_cannot_begin_while_waiting_for_a_result(self, session, monkeypatch):
        """还在等上一句的识别结果时不该开始录下一句 ——
        结果回来时会对不上号。"""
        install(monkeypatch, FakeRecorder())
        session.begin("paste", None, 120.0)
        session.finish("paste")
        assert session.is_busy
        assert session.begin("paste", None, 120.0) is False

    def test_device_failure_is_reported_not_swallowed(self, session, monkeypatch):
        def boom(**kw):
            raise RecordingError("麦克风打不开")

        monkeypatch.setattr("voiceinput.session.Recorder", boom)
        failures = []
        session.failed.connect(failures.append)

        assert session.begin("paste", None, 120.0) is False
        assert failures == ["麦克风打不开"]
        assert not session.is_recording


class TestFinish:
    def test_emits_audio_with_the_real_sample_rate(self, session, monkeypatch):
        """**必须是实际录音用的速率**,不能写死 16000。
        按 48k 录完却声明 16k,识别会悄悄变差而不是报错。"""
        install(monkeypatch, FakeRecorder(sample_rate=48000))
        got = []
        session.ready.connect(lambda a, sr, act: got.append((sr, act)))

        session.begin("paste", None, 120.0)
        session.finish("paste_and_send")
        assert got == [(48000, "paste_and_send")]

    def test_empty_audio_fails(self, session, monkeypatch):
        install(monkeypatch, FakeRecorder(audio=np.zeros(0, dtype=np.float32)))
        failures = []
        session.failed.connect(failures.append)
        session.begin("paste", None, 120.0)
        session.finish("paste")
        assert failures and "没有录到音频" in failures[0]

    def test_silence_fails_loudly(self, session, monkeypatch):
        """最常见的"以为成功其实失败":设备选错、麦克风静音、离得太远。"""
        install(monkeypatch, FakeRecorder(audio=np.zeros(16000, dtype=np.float32)))
        failures = []
        session.failed.connect(failures.append)
        session.begin("paste", None, 120.0)
        session.finish("paste")
        assert failures and "静音" in failures[0]

    def test_silence_does_not_leave_busy_set(self, session, monkeypatch):
        """失败之后必须能马上再录 —— 卡在 busy 就等于热键失效。"""
        install(monkeypatch, FakeRecorder(audio=np.zeros(16000, dtype=np.float32)))
        session.begin("paste", None, 120.0)
        session.finish("paste")
        assert session.is_idle

    def test_finish_without_recording_is_safe(self, session):
        got = []
        session.ready.connect(lambda *a: got.append(a))
        session.finish("paste")
        assert got == []


class TestWarning:
    def test_truncation_is_reported(self, session, monkeypatch):
        """被削过的音频识别出来看着是完整一句话,不说用户发现不了。"""
        install(monkeypatch, FakeRecorder(truncated=True, max_seconds=30.0))
        session.begin("paste", None, 30.0)
        session.finish("paste")
        assert "30 秒上限" in session.take_warning()

    def test_overflow_is_reported(self, session, monkeypatch):
        install(monkeypatch, FakeRecorder(overflowed=True))
        session.begin("paste", None, 120.0)
        session.finish("paste")
        assert "丢帧" in session.take_warning()

    def test_warning_is_said_only_once(self, session, monkeypatch):
        install(monkeypatch, FakeRecorder(overflowed=True))
        session.begin("paste", None, 120.0)
        session.finish("paste")
        assert session.take_warning()
        assert session.take_warning() == ""

    def test_clean_recording_has_no_warning(self, session, monkeypatch):
        install(monkeypatch, FakeRecorder())
        session.begin("paste", None, 120.0)
        session.finish("paste")
        assert session.take_warning() == ""


class TestWatchdog:
    def test_settle_releases_busy(self, session, monkeypatch):
        install(monkeypatch, FakeRecorder())
        session.begin("paste", None, 120.0)
        session.finish("paste")
        session.settle()
        assert session.is_idle

    def test_timeout_releases_busy_and_says_so(self, session, monkeypatch):
        install(monkeypatch, FakeRecorder())
        timeouts = []
        session.timedOut.connect(timeouts.append)

        session.begin("paste", None, 120.0)
        session.finish("paste")
        session._on_timeout()

        assert session.is_idle, "busy 卡住会让热键彻底静默失效"
        assert timeouts and "超时" in timeouts[0]

    def test_timeout_after_result_is_a_noop(self, session):
        """结果已经回来了,看门狗晚一步触发不该凭空报错。"""
        timeouts = []
        session.timedOut.connect(timeouts.append)
        session._on_timeout()
        assert timeouts == []

    def test_timeout_is_generous(self):
        """正常识别 0.3 秒。超时值要远大于它,否则会误杀慢一点的机器。"""
        assert TRANSCRIBE_TIMEOUT_MS >= 10_000


class TestAbort:
    def test_stops_everything(self, session, monkeypatch):
        rec = FakeRecorder()
        install(monkeypatch, rec)
        session.begin("paste", None, 120.0)
        session.abort()
        assert rec.stopped
        assert session.is_idle
