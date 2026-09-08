"""设备提示文案必须来自运行时枚举,不能写死开发机的情况。

原来设置页和向导里各写着一句:
"这台机器所有输入设备都是 RØDE Connect 的虚拟设备,系统默认的
「System Input」很可能是系统声音回环"。

那是**开发机**的情况。换台机器就是错的,还会让人以为程序认错了硬件。
"""

import pytest

from voiceinput.audio import Device, looks_like_loopback, suspicious_devices
from voiceinput.ui import device_picker


class TestLooksLikeLoopback:
    @pytest.mark.parametrize("name", [
        "System Input (RØDE Connect)",
        "立体声混音 (Realtek High Definition Audio)",
        "Stereo Mix",
        "CABLE Output (VB-Audio Virtual Cable)",
        "VoiceMeeter Output",
        "What U Hear",
    ])
    def test_flags_known_loopback_shapes(self, name):
        assert looks_like_loopback(name)

    @pytest.mark.parametrize("name", [
        "Microphone (Realtek High Definition Audio)",
        "麦克风 (USB Audio Device)",
        "Blue Yeti",
        "Headset Microphone",
    ])
    def test_leaves_real_microphones_alone(self, name):
        assert not looks_like_loopback(name)

    def test_case_insensitive(self):
        assert looks_like_loopback("STEREO MIX")

    def test_is_only_a_hint_not_a_gate(self):
        """**这个判断不用来禁用任何设备。**

        名字是厂商随便起的,列表永远列不全,真话筒也可能撞上这些词。
        唯一可靠的判据是看电平 —— 所以它只决定"要不要多提醒一句"。
        这条测试钉住的是这个约定:函数返回布尔,不返回"可用/不可用"。
        """
        assert looks_like_loopback("Stereo Mix") is True
        assert looks_like_loopback("Blue Yeti") is False


class TestSuspiciousDevices:
    def test_filters_a_given_list(self):
        devices = [
            Device(0, "Blue Yeti", "MME", 2),
            Device(1, "Stereo Mix", "MME", 2),
        ]
        assert [d.name for d in suspicious_devices(devices)] == ["Stereo Mix"]

    def test_empty_list_is_fine(self):
        assert suspicious_devices([]) == []


class TestDeviceHint:
    def base_text(self):
        return device_picker._BASE_HINT

    def test_clean_machine_gets_the_plain_hint(self, monkeypatch):
        monkeypatch.setattr(device_picker.audio_mod, "suspicious_devices",
                            lambda *_: [])
        assert device_picker.device_hint() == self.base_text()

    def test_names_the_actual_suspects(self, monkeypatch):
        monkeypatch.setattr(
            device_picker.audio_mod, "suspicious_devices",
            lambda *_: [Device(1, "Stereo Mix", "MME", 2)])
        text = device_picker.device_hint()
        assert "Stereo Mix" in text
        assert self.base_text() in text

    def test_does_not_mention_the_dev_machine(self, monkeypatch):
        """开发机的硬件名不该出现在任何用户看得见的地方。"""
        monkeypatch.setattr(
            device_picker.audio_mod, "suspicious_devices",
            lambda *_: [Device(1, "Stereo Mix", "MME", 2)])
        text = device_picker.device_hint()
        assert "RØDE" not in text and "D2R" not in text

    def test_deduplicates_names(self, monkeypatch):
        """同一个设备在 MME 和 WASAPI 下各出现一次,名字一样 ——
        提示里不能把同一个名字念两遍。"""
        monkeypatch.setattr(
            device_picker.audio_mod, "suspicious_devices",
            lambda *_: [Device(1, "System Input", "MME", 2),
                        Device(5, "System Input", "Windows WASAPI", 2)])
        assert device_picker.device_hint().count("「System Input」") == 1

    def test_enumeration_failure_still_gives_a_hint(self, monkeypatch):
        """枚举失败(没有声卡、驱动坏了)不该连提示都没有。"""
        def boom(*_):
            raise OSError("no audio device")

        monkeypatch.setattr(device_picker.audio_mod, "suspicious_devices", boom)
        assert device_picker.device_hint() == self.base_text()
