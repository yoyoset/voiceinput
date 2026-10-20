"""设置页的麦克风预选:按名字,不按缓存的编号。

2026-10-04 实际出过的事故:存的话筒(TASCAM)不在线时,它的 1 号被系统回环
顶了;下拉框照着编号选中回环,随后改了一个不相干的设置,回环就被存成了
"用户选的话筒"。话筒插回来后 1 号又是它 —— 界面显示话筒,实际按名字录的
是回环,每次都是"只录到静音"。
"""

from unittest.mock import patch

from voiceinput.audio import Device
from voiceinput.config import Config
from voiceinput.ui import theme
from voiceinput.ui.pages.audio import AudioPage

MIC = "麦克风 (TASCAM DR Series)"
LOOPBACK = "System Input (RØDE Connect)"

MIC_UNPLUGGED = [
    Device(1, LOOPBACK, "MME", 2),
    Device(2, "Virtual Input (RØDE Connect)", "MME", 2),
]
MIC_PLUGGED = [
    Device(1, MIC, "MME", 2),
    Device(3, LOOPBACK, "MME", 2),
]


def make_cfg(index, name, hostapi="MME") -> Config:
    cfg = Config()
    cfg.audio.device, cfg.audio.device_name, cfg.audio.device_hostapi = \
        index, name, hostapi
    return cfg


def test_absent_mic_survives_unrelated_change(qapp):
    """话筒暂时不在线时改别的设置,不能把它的名字换成占了它编号的设备。"""
    cfg = make_cfg(1, MIC)
    with patch("voiceinput.audio.list_devices", return_value=MIC_UNPLUGGED):
        page = AudioPage(cfg, theme.DARK)
        assert page.picker.device() is None      # 不冒充成回环
        page.collect(cfg)
    assert (cfg.audio.device_name, cfg.audio.device_hostapi) == (MIC, "MME")


def test_explicit_pick_replaces_absent_mic(qapp):
    """不在线期间用户亲手换了设备,那就以他选的为准。"""
    cfg = make_cfg(1, MIC)
    with patch("voiceinput.audio.list_devices", return_value=MIC_UNPLUGGED):
        page = AudioPage(cfg, theme.DARK)
        page.picker.combo.setCurrentIndex(page.picker.combo.findData(2))
        page.collect(cfg)
    assert cfg.audio.device_name == "Virtual Input (RØDE Connect)"
    assert cfg.audio.device == 2


def test_shows_what_is_actually_recorded(qapp):
    """缓存编号指着别的设备时,下拉框显示的必须是按名字找到的那个。"""
    cfg = make_cfg(1, LOOPBACK)                  # 1 号现在是 TASCAM
    with patch("voiceinput.audio.list_devices", return_value=MIC_PLUGGED):
        page = AudioPage(cfg, theme.DARK)
        assert page.picker.device() == 3
        assert page.picker.device_identity() == (LOOPBACK, "MME")
