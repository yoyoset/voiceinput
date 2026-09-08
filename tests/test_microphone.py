"""配置里的麦克风 → 当前这一刻的设备编号。

**存的编号只是缓存,名字才是身份。** PortAudio 的 index 是枚举序号,
插拔任何一个音频设备都会重排;认编号会在某天悄悄录到别的设备上,
而录错设备的表现是"按了热键没反应"或"只录到静音" ——
用户根本不会想到是编号漂了。

所以"漂了"这件事必须能说出来。
"""

import pytest

from voiceinput.config import Config
from voiceinput.microphone import Microphone


@pytest.fixture
def mic(qapp):
    return Microphone()


def fake_resolve(monkeypatch, result, calls=None):
    def resolve(index, name, hostapi):
        if calls is not None:
            calls.append((index, name, hostapi))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("voiceinput.microphone.resolve_device", resolve)


class TestApply:
    def test_resolves_on_first_apply(self, mic, monkeypatch):
        fake_resolve(monkeypatch, (7, ""))
        mic.apply(Config())
        assert mic.index == 7

    def test_same_config_is_not_re_resolved(self, mic, monkeypatch):
        """枚举音频设备不便宜,而配置保存是防抖后批量发的 ——
        一次改动会走好几遍这条路。"""
        calls = []
        fake_resolve(monkeypatch, (7, ""), calls)
        mic.apply(Config())
        mic.apply(Config())
        assert len(calls) == 1

    def test_changed_device_re_resolves(self, mic, monkeypatch):
        calls = []
        fake_resolve(monkeypatch, (7, ""), calls)
        mic.apply(Config())
        cfg = Config()
        cfg.audio.device_name = "Blue Yeti"
        mic.apply(cfg)
        assert len(calls) == 2

    def test_unrelated_change_does_not_re_resolve(self, mic, monkeypatch):
        calls = []
        fake_resolve(monkeypatch, (7, ""), calls)
        mic.apply(Config())
        cfg = Config()
        cfg.ui.theme = "dark"
        mic.apply(cfg)
        assert len(calls) == 1

    def test_name_and_hostapi_are_both_passed_through(self, mic, monkeypatch):
        """同一个物理设备在多个 hostapi 下同名各出现一次 ——
        只认名字会挑错那一个。"""
        calls = []
        fake_resolve(monkeypatch, (3, ""), calls)
        cfg = Config()
        cfg.audio.device = 1
        cfg.audio.device_name = "Blue Yeti"
        cfg.audio.device_hostapi = "Windows WASAPI"
        mic.apply(cfg)
        assert calls == [(1, "Blue Yeti", "Windows WASAPI")]


class TestNote:
    def test_note_is_announced(self, mic, monkeypatch):
        """**悄悄换设备是这个项目最忌讳的事。**"""
        fake_resolve(monkeypatch, (2, "原来选的设备没了,改用系统默认"))
        seen = []
        mic.noteChanged.connect(seen.append)
        mic.apply(Config())
        assert seen and "系统默认" in seen[0]

    def test_no_note_when_everything_is_fine(self, mic, monkeypatch):
        fake_resolve(monkeypatch, (7, ""))
        seen = []
        mic.noteChanged.connect(seen.append)
        mic.apply(Config())
        assert seen == []


class TestEnumerationFailure:
    def test_failure_falls_back_to_the_configured_index(self, mic, monkeypatch):
        """枚举设备失败不该拦住启动 —— 退回配置里存的编号,试试再说。"""
        fake_resolve(monkeypatch, OSError("PortAudio 挂了"))
        cfg = Config()
        cfg.audio.device = 5
        mic.apply(cfg)
        assert mic.index == 5

    def test_failure_says_nothing_to_the_user(self, mic, monkeypatch):
        """这条只该进日志。用户什么都没改,弹一句他看不懂的话没有意义 ——
        真出问题时会在"只录到静音"那里被告知。"""
        fake_resolve(monkeypatch, OSError("boom"))
        seen = []
        mic.noteChanged.connect(seen.append)
        mic.apply(Config())
        assert seen == []
