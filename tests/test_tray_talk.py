"""单击托盘图标说话。

用户的原话:图标在通知栏里,"即便是固定在这儿,我也没有办法通过点击它来说话"。
两件要钉住的事:

1. 单击 = 开始/结束,而且**双击不能变成"刚开始就结束"**;
2. 点托盘会抢焦点(2026-09-24 实测),**必须先把焦点还给原窗口,等它落定,
   再开始/结束** —— 不然开始时记下的目标是任务栏,文字没处贴。
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QSystemTrayIcon

from voiceinput import app as app_mod
from voiceinput.app import App
from voiceinput.config import Config
from voiceinput.ui.main_window import MainWindow
from voiceinput.ui.theme import apply_theme
from voiceinput.ui.tray import Tray

R = QSystemTrayIcon.ActivationReason


@pytest.fixture
def tray(qapp):
    return Tray(apply_theme(qapp, "dark"))


def record(tray):
    got = []
    tray.talkRequested.connect(lambda: got.append("talk"))
    tray.openRequested.connect(lambda: got.append("open"))
    return got


def set_mode(tray, mode):
    cfg = Config()
    cfg.ui.tray_click = mode
    tray.apply(cfg)


def test_默认单击还是打开窗口(tray):
    """老用户升级后行为不能悄悄变。"""
    got = record(tray)
    tray._on_activated(R.Trigger)
    assert got == ["open"]


def test_单击说话模式下单击就是说话(tray):
    set_mode(tray, "talk")
    got = record(tray)
    tray._on_activated(R.Trigger)
    assert got == ["talk"]


def test_双击不会把刚开始的录音结束掉(tray):
    """双击的第一下已经发过 Trigger;再响应 DoubleClick 就等于开了又关。"""
    set_mode(tray, "talk")
    got = record(tray)
    tray._on_activated(R.Trigger)
    tray._on_activated(R.DoubleClick)
    assert got == ["talk"]


def test_单击说话模式下中键打开设置(tray):
    set_mode(tray, "talk")
    got = record(tray)
    tray._on_activated(R.MiddleClick)
    assert got == ["open"]


def test_设置页能选这一项(qapp):
    cfg = Config()
    cfg.ui.tray_click = "talk"
    win = MainWindow(cfg, apply_theme(qapp, "dark"), None)
    assert win.general.tray_click.currentData() == "talk"
    out = Config()
    win.general.collect(out)
    assert out.ui.tray_click == "talk"
    win.deleteLater()


# ---- 还焦点 ----


class FakeFocus:
    def __init__(self, last):
        self.last_target = last


class FakeApp:
    def __init__(self, last):
        self.focus = FakeFocus(last)
        self.toggled = 0

    def _toggle_from_badge(self):
        self.toggled += 1

    _toggle_from_tray = App._toggle_from_tray


def test_先还焦点等落定再开始(qapp, monkeypatch):
    """实测 SetForegroundWindow 返回后前台不是立刻变过去的,要等。"""
    activated = []
    fg = {"now": 0}
    monkeypatch.setattr(app_mod, "activate_window", lambda h: activated.append(h) or True)
    monkeypatch.setattr(app_mod, "foreground_window", lambda: fg["now"])
    app = FakeApp(last=555)
    app._toggle_from_tray()
    assert activated == [555]
    assert app.toggled == 0, "焦点还没回来就开始,记下的目标会是任务栏"
    fg["now"] = 555
    qapp.processEvents()
    import time
    deadline = time.time() + 1
    while app.toggled == 0 and time.time() < deadline:
        qapp.processEvents()
    assert app.toggled == 1


def test_还不回去也照常录不静默(monkeypatch):
    """拿不到原窗口时不能什么都不做 —— 用户点了没反应比贴不进去更糟;
    贴的时候 Delivery 会把文字留在剪贴板并提示。"""
    monkeypatch.setattr(app_mod, "activate_window", lambda h: False)
    app = FakeApp(last=None)
    app._toggle_from_tray()
    assert app.toggled == 1
