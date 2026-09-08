"""Recorder 的截断/丢帧检测。

这两件事原来是**完全静默**的:超过单次上限后音频被直接丢弃、PortAudio 报的
input_overflow 被整个忽略。结果是用户说了三分钟只转了前两分钟、或者中间掉了
几秒,而识别结果看着是完整一句话,根本发现不了。

不碰真麦克风:直接喂 _callback,它就是个纯粹的数据入口。

构造 Recorder 时**显式给 sample_rate**:默认值是"跟设备走",
那会让这些测试依赖本机声卡的原生速率(这台机器是 44100),
帧数算出来和 feed() 对不上。测试不该依赖硬件。
"""

import numpy as np
import pytest

from voiceinput.audio import Recorder, rms_dbfs, looks_silent


class FakeStatus:
    """模拟 sounddevice 的 CallbackFlags。"""

    def __init__(self, input_overflow: bool = False) -> None:
        self.input_overflow = input_overflow

    def __bool__(self) -> bool:
        return self.input_overflow


def feed(rec: Recorder, seconds: float, status=None, sample_rate: int = 16000) -> None:
    frames = int(seconds * sample_rate)
    block = np.zeros((frames, 1), dtype=np.float32)
    rec._callback(block, frames, None, status)


class TestTruncation:
    def test_not_truncated_under_limit(self):
        rec = Recorder(sample_rate=16000, max_seconds=10.0)
        feed(rec, 5.0)
        assert not rec.truncated
        assert rec.duration_seconds == pytest.approx(5.0)

    def test_truncated_over_limit(self):
        rec = Recorder(sample_rate=16000, max_seconds=10.0)
        feed(rec, 10.0)
        feed(rec, 1.0)          # 这一段应该被丢掉并留下痕迹
        assert rec.truncated

    def test_duration_stops_at_limit(self):
        """超限后 duration 不再增长——丢掉的部分不该算进已录时长。"""
        rec = Recorder(sample_rate=16000, max_seconds=10.0)
        feed(rec, 10.0)
        feed(rec, 5.0)
        assert rec.duration_seconds == pytest.approx(10.0)

    def test_max_seconds_property(self):
        assert Recorder(sample_rate=16000, max_seconds=42.0).max_seconds == pytest.approx(42.0)

    def test_reset_on_start_is_independent_of_stream(self):
        """标志位是"本次录音"的状态,不能跨次残留。"""
        rec = Recorder(sample_rate=16000, max_seconds=1.0)
        feed(rec, 2.0)
        assert rec.truncated
        # 模拟重新开始(不真的开流)
        rec._frames = 0
        rec._truncated = False
        rec._overflowed = False
        assert not rec.truncated


class TestOverflow:
    def test_clean_status_no_overflow(self):
        rec = Recorder(sample_rate=16000, max_seconds=10.0)
        feed(rec, 1.0, status=FakeStatus(False))
        assert not rec.overflowed

    def test_none_status_no_overflow(self):
        rec = Recorder(sample_rate=16000, max_seconds=10.0)
        feed(rec, 1.0, status=None)
        assert not rec.overflowed

    def test_overflow_flagged(self):
        rec = Recorder(sample_rate=16000, max_seconds=10.0)
        feed(rec, 1.0, status=FakeStatus(True))
        assert rec.overflowed

    def test_overflow_sticks(self):
        """溢出发生过就得记住,后面正常了也不能抹掉——音频确实缺了。"""
        rec = Recorder(sample_rate=16000, max_seconds=10.0)
        feed(rec, 1.0, status=FakeStatus(True))
        feed(rec, 1.0, status=FakeStatus(False))
        assert rec.overflowed

    def test_overflow_recorded_even_when_truncated(self):
        """已经超限的回调也要读 status,否则末尾的溢出会漏掉。"""
        rec = Recorder(sample_rate=16000, max_seconds=1.0)
        feed(rec, 2.0)
        assert rec.truncated
        feed(rec, 1.0, status=FakeStatus(True))
        assert rec.overflowed


class TestLevels:
    def test_silence_is_negative_infinity(self):
        assert rms_dbfs(np.zeros(1000, dtype=np.float32)) == float("-inf")

    def test_empty_array(self):
        assert rms_dbfs(np.zeros(0, dtype=np.float32)) == float("-inf")

    def test_full_scale_is_zero_dbfs(self):
        assert rms_dbfs(np.ones(1000, dtype=np.float32)) == pytest.approx(0.0)

    def test_half_scale(self):
        assert rms_dbfs(np.full(1000, 0.5, dtype=np.float32)) == pytest.approx(-6.02, abs=0.1)

    def test_looks_silent(self):
        assert looks_silent(np.zeros(1000, dtype=np.float32))
        assert not looks_silent(np.full(1000, 0.2, dtype=np.float32))

    def test_quiet_but_not_silent(self):
        """-40 dBFS 是很轻但真实的说话声,不能判成静音。"""
        assert not looks_silent(np.full(1000, 0.01, dtype=np.float32))


class TestNativeSampleRate:
    """**不能写死 16000 开流。**

    WASAPI 共享模式只接受设备原生速率,请求别的直接报
    `Invalid sample rate [PaErrorCode -9997]`。本机 WASAPI 设备原生是 48000 ——
    也就是说曾经**选中任何一个 WASAPI 设备都录不了音**,
    而设置界面里一半的选项都是 WASAPI。

    录进来之后按**真实**速率交给引擎,sherpa-onnx 自己重采样;
    实测 16k / 44.1k / 48k 三种输入识别结果逐字相同。
    但**谎报**速率会让识别悄悄变差,所以 Recorder 必须把实际速率报出来。
    """

    def test_recorder_uses_device_rate_by_default(self, monkeypatch):
        monkeypatch.setattr("voiceinput.audio.native_sample_rate", lambda d: 48000)
        rec = Recorder(device=29)
        assert rec.sample_rate == 48000

    def test_explicit_rate_wins(self, monkeypatch):
        monkeypatch.setattr("voiceinput.audio.native_sample_rate", lambda d: 48000)
        assert Recorder(device=29, sample_rate=16000).sample_rate == 16000

    def test_max_frames_follows_actual_rate(self, monkeypatch):
        """上限是按秒配的,不同速率下帧数不同 —— 用错速率会让上限差三倍。"""
        monkeypatch.setattr("voiceinput.audio.native_sample_rate", lambda d: 48000)
        rec = Recorder(device=29, max_seconds=10.0)
        assert rec.max_seconds == pytest.approx(10.0)
        assert rec._max_frames == 480_000

    def test_duration_uses_actual_rate(self, monkeypatch):
        monkeypatch.setattr("voiceinput.audio.native_sample_rate", lambda d: 48000)
        rec = Recorder(device=29, max_seconds=10.0)
        feed(rec, 1.0, sample_rate=48000)
        assert rec.duration_seconds == pytest.approx(1.0)

    def test_falls_back_when_query_fails(self, monkeypatch):
        """查不到设备信息时退回 16000,不该让构造直接崩。"""
        import voiceinput.audio as a

        monkeypatch.setattr(a.sd, "query_devices",
                            lambda *args, **kw: (_ for _ in ()).throw(OSError("no")))
        assert a.native_sample_rate(999) == a.SAMPLE_RATE

    def test_zero_rate_falls_back(self, monkeypatch):
        import voiceinput.audio as a

        monkeypatch.setattr(a.sd, "query_devices",
                            lambda *args, **kw: {"default_samplerate": 0})
        assert a.native_sample_rate(1) == a.SAMPLE_RATE
