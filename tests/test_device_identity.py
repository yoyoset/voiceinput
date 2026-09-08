"""设备身份:按名字认设备,不认编号。

**编号会漂。** PortAudio 的 index 是枚举序号,插拔任何一个音频设备
(插个 USB 耳机、开关虚拟声卡)都会重排。存 29 号,过几天 29 号可能
已经是别的东西了 —— 于是录音悄悄录到别的设备上,表现是"按了热键没反应"
或"只录到静音",用户根本不会想到是编号漂了。

这也让 README 里"整个目录拷走即可在别的机器上跑"这句话真正成立:
换机器时编号肯定对不上,名字还有机会对上。
"""

from unittest.mock import patch

import pytest

from voiceinput.audio import Device, resolve_device

# 模拟"插了新设备之后编号整体后移"
BEFORE = [
    Device(1, "System Input (RØDE Connect)", "MME", 2),
    Device(29, "System Input (RØDE Connect)", "Windows WASAPI", 2),
    Device(30, "Virtual Input (RØDE Connect)", "Windows WASAPI", 2),
]
AFTER_PLUGGING_IN = [
    Device(1, "USB Headset", "MME", 2),
    Device(31, "System Input (RØDE Connect)", "Windows WASAPI", 2),
    Device(32, "Virtual Input (RØDE Connect)", "Windows WASAPI", 2),
]


def resolve(devices, index, name="", hostapi=""):
    with patch("voiceinput.audio.list_devices", return_value=devices):
        return resolve_device(index, name, hostapi)


class TestFollowsName:
    def test_index_unchanged_when_nothing_moved(self):
        idx, note = resolve(BEFORE, 29, "System Input (RØDE Connect)", "Windows WASAPI")
        assert idx == 29
        assert note == ""

    def test_finds_device_after_index_shift(self):
        """核心场景:插了个 USB 耳机,编号整体后移,还得找到原来那个。"""
        idx, note = resolve(AFTER_PLUGGING_IN, 29,
                            "System Input (RØDE Connect)", "Windows WASAPI")
        assert idx == 31, "应该按名字找回,而不是继续用漂掉的 29"
        assert note == ""

    def test_does_not_grab_someone_elses_index(self):
        """漂移之后 29 号可能是别的设备 —— 绝不能将错就错用下去。"""
        idx, _ = resolve(AFTER_PLUGGING_IN, 1, "System Input (RØDE Connect)",
                         "Windows WASAPI")
        assert idx != 1, "1 号现在是 USB Headset,不能录到它上面去"

    def test_hostapi_disambiguates_same_name(self):
        """同一个设备在多个 hostapi 下名字完全相同,只认名字会挑错。"""
        idx, _ = resolve(BEFORE, None, "System Input (RØDE Connect)", "MME")
        assert idx == 1
        idx, _ = resolve(BEFORE, None, "System Input (RØDE Connect)", "Windows WASAPI")
        assert idx == 29


class TestFallbacks:
    def test_no_name_keeps_index(self):
        """老配置里没存名字,只能沿用编号。"""
        idx, note = resolve(BEFORE, 29)
        assert idx == 29
        assert note == ""

    def test_system_default_stays_default(self):
        idx, note = resolve(BEFORE, None)
        assert idx is None
        assert note == ""

    def test_hostapi_changed_still_resolves_with_note(self):
        """接口变了但设备还在 —— 用它,但要说一声。"""
        idx, note = resolve(AFTER_PLUGGING_IN, 1,
                            "System Input (RØDE Connect)", "MME")
        assert idx == 31
        assert "接口" in note

    def test_missing_device_falls_back_to_default_and_says_so(self):
        """设备拔了。**必须明说**,不能默默用系统默认 ——
        那台机器上的系统默认很可能是系统声音回环。"""
        idx, note = resolve(AFTER_PLUGGING_IN, 29, "拔掉了的麦克风", "Windows WASAPI")
        assert idx is None
        assert "找不到" in note
        assert "重新选择" in note

    def test_empty_device_list(self):
        idx, note = resolve([], 29, "任何设备", "MME")
        assert idx is None
        assert note

    @pytest.mark.parametrize("hostapi", ["", "Windows WASAPI"])
    def test_name_alone_is_enough_when_unique(self, hostapi):
        idx, _ = resolve(BEFORE, None, "Virtual Input (RØDE Connect)", hostapi)
        assert idx == 30
