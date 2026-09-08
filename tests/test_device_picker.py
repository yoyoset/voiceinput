"""设备选择组件。设置页和向导共用的那一份。

抽出来之前两边各写一份,提示文案已经漂移成两种措辞了。
这组测试钉住的是**判断"这到底是不是话筒"的那套结论**,
因为那是这台机器上最容易选错、且选错后表现为"按了热键没反应"的地方。
"""

from unittest.mock import patch

import pytest

from voiceinput.audio import Device, RecordingError
from voiceinput.ui import theme
from voiceinput.ui.device_picker import DevicePicker


FAKE_DEVICES = [
    Device(1, "System Input (RØDE Connect)", "MME", 2),
    Device(29, "System Input (RØDE Connect)", "Windows WASAPI", 2),
]


@pytest.fixture
def picker(qapp):
    with patch("voiceinput.audio.list_devices", return_value=FAKE_DEVICES):
        yield DevicePicker(theme.DARK)


class FakeMonitor:
    def __init__(self, level=-20.0, fail=False) -> None:
        self._level = level
        self._fail = fail
        self.started = self.stopped = False

    @property
    def level_dbfs(self) -> float:
        return self._level

    def start(self) -> None:
        if self._fail:
            raise RecordingError("打不开麦克风: 设备被占用")
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class TestDeviceList:
    def test_lists_devices(self, picker):
        assert picker.combo.count() == len(FAKE_DEVICES) + 1   # +系统默认

    def test_default_is_first_and_discouraged(self, picker):
        """系统默认排第一但要标"不推荐" —— 这台机器上它多半是系统回环。"""
        assert picker.combo.itemData(0) is None
        assert "不推荐" in picker.combo.itemText(0)

    def test_hostapi_shown(self, picker):
        """同名设备在多个 hostapi 下各出现一次,不标出来根本分不清。"""
        assert "WASAPI" in picker.combo.itemText(2)

    def test_preselects_given_device(self, qapp):
        with patch("voiceinput.audio.list_devices", return_value=FAKE_DEVICES):
            p = DevicePicker(theme.DARK, device=29)
        assert p.device() == 29

    def test_unknown_device_falls_back_to_default(self, qapp):
        """配置里存的设备被拔掉了,不能让下拉框空着。"""
        with patch("voiceinput.audio.list_devices", return_value=FAKE_DEVICES):
            p = DevicePicker(theme.DARK, device=999)
        assert p.device() is None

    def test_enumeration_failure_is_visible(self, qapp):
        with patch("voiceinput.audio.list_devices", side_effect=OSError("驱动挂了")):
            p = DevicePicker(theme.DARK)
        assert any("枚举设备失败" in p.combo.itemText(i) for i in range(p.combo.count()))

    def test_reload_keeps_selection(self, picker):
        picker.combo.setCurrentIndex(2)
        chosen = picker.device()
        with patch("voiceinput.audio.list_devices", return_value=FAKE_DEVICES):
            picker.reload_devices()
        assert picker.device() == chosen


class TestMonitor:
    def test_start_stop(self, picker):
        mon = FakeMonitor()
        with patch("voiceinput.audio.LevelMonitor", return_value=mon):
            assert picker.start_monitor()
        assert picker.monitoring and mon.started
        picker.stop_monitor()
        assert not picker.monitoring and mon.stopped

    def test_start_failure_is_shown_not_swallowed(self, picker):
        """麦克风打不开必须看得见 —— 静默失败会让用户以为是别的问题。"""
        with patch("voiceinput.audio.LevelMonitor", return_value=FakeMonitor(fail=True)):
            assert picker.start_monitor() is False
        assert "打不开麦克风" in picker.hint.text()
        assert picker.hint.property("role") == "danger"

    def test_double_start_is_safe(self, picker):
        with patch("voiceinput.audio.LevelMonitor", return_value=FakeMonitor()):
            picker.start_monitor()
            assert picker.start_monitor()

    def test_stop_without_start_is_safe(self, picker):
        picker.stop_monitor()
        assert not picker.monitoring


class TestVerdict:
    """有电平 ≠ 是话筒。系统声音回环同样有电平。"""

    def set_level(self, picker, dbfs):
        with patch("voiceinput.audio.LevelMonitor", return_value=FakeMonitor(dbfs)):
            picker.start_monitor()
        picker._poll()

    def test_loud_enough_is_ok(self, picker):
        self.set_level(picker, -20.0)
        assert "有信号" in picker.hint.text()
        assert picker.hint.property("role") == "hint"

    def test_too_quiet_warns_about_wrong_device(self, picker):
        self.set_level(picker, -60.0)
        assert "可能不是话筒" in picker.hint.text()
        assert picker.hint.property("role") == "danger"

    def test_no_signal_at_all(self, picker):
        self.set_level(picker, float("-inf"))
        assert "没有信号" in picker.hint.text()

    def test_threshold_boundary(self, picker):
        """-50 dBFS 是分界。刚过线就该算有信号,否则提示会一直吓唬人。"""
        self.set_level(picker, -49.0)
        assert "有信号" in picker.hint.text()


class TestDeviceChange:
    def test_emits_signal(self, picker):
        got = []
        picker.deviceChanged.connect(got.append)
        picker.combo.setCurrentIndex(2)
        assert got == [29]

    def test_restarts_monitor_on_change(self, picker):
        """换设备后监听要接到新设备上,不能还连着旧的。"""
        first, second = FakeMonitor(), FakeMonitor()
        with patch("voiceinput.audio.LevelMonitor", return_value=first):
            picker.start_monitor()
        with patch("voiceinput.audio.LevelMonitor", return_value=second):
            picker.combo.setCurrentIndex(2)
        assert first.stopped
        assert second.started

    def test_does_not_start_monitor_if_not_running(self, picker):
        """本来没在测,换个设备不该凭空开始占用麦克风。"""
        picker.combo.setCurrentIndex(2)
        assert not picker.monitoring
