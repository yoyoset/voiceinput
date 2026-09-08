"""悬浮麦克风的右键菜单,和「说完直接发送」这个开关。

三件用户当面提的事:

1. 桌面上一个圆按钮,出了问题**第一反应就是右键点它** —— 以前右键
   什么都不发生,唯一的出路是去托盘里找那个很小的图标。
2. 说完能不能**直接发送**,而不是粘完还要自己按回车。
3. 这个开关在两处露面(右键菜单、设置页),两处必须一致 ——
   而两处互相写配置最容易绕成一个死循环。
"""

from __future__ import annotations

import pytest

from voiceinput.app import App
from voiceinput.config import Config
from voiceinput.ui.main_window import MainWindow
from voiceinput.ui.mic_badge import MicBadge
from voiceinput.ui.theme import apply_theme
from voiceinput.ui.tray import Tray


@pytest.fixture
def parts(qapp):
    pal = apply_theme(qapp, "dark")
    tray, badge = Tray(pal), MicBadge(pal)
    yield tray, badge, qapp
    badge.deleteLater()


# ---- 右键菜单 ----


def test_右键弹的是托盘那一份菜单(parts):
    """**不能另建一份。** 两份菜单会漂移成不一样的选项,
    而且是那种没人会发现的漂移:很少有人会同时右键托盘和右键悬浮麦克风。
    """
    tray, badge, _ = parts
    badge.set_menu(tray.contextMenu())
    assert badge._menu is tray.contextMenu()


def test_没设过菜单时右键不会炸(parts):
    """自检和 bench 里会单独造 MicBadge,那时没有托盘。"""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    _, badge, _ = parts
    ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                           QPoint(5, 5), QPoint(5, 5))
    badge.contextMenuEvent(ev)      # 不抛就算过


def test_菜单里能找到设置和退出(parts):
    """右键的意义就在于不用去托盘里找。菜单里必须有出路。"""
    tray, _, _ = parts
    labels = [a.text() for a in tray.contextMenu().actions()]
    assert "设置与历史" in labels
    assert "退出" in labels


# ---- 说完直接发送 ----


def test_默认只粘贴不发送():
    """**回车是不可撤销的** —— 识别错了也已经发出去了。默认必须是关的。"""
    assert Config().ui.badge_action == "paste"


def test_勾上菜单项就改配置(parts):
    tray, _, _ = parts
    seen = []
    tray.sendAfterChanged.connect(seen.append)
    tray._act_send.setChecked(True)
    assert seen == [True]


def test_配置回灌不会再发一次信号(parts):
    """**这里是最容易绕成死循环的地方。**

    设置页改了这一项 → 配置分发到托盘 → 勾一变又发 sendAfterChanged →
    又写一次配置 → 又分发…… 所以 `apply()` 必须挡住信号。
    """
    tray, _, _ = parts
    seen = []
    tray.sendAfterChanged.connect(seen.append)

    cfg = Config()
    cfg.ui.badge_action = "paste_and_send"
    tray.apply(cfg)

    assert tray._act_send.isChecked() is True
    assert seen == [], "配置回灌反弹出了一次信号,这就是死循环的第一圈"


def test_菜单和设置页显示的是同一件事(qapp):
    """开关在两处露面,两处得说同一句话 —— 否则用户在设置页看到"只粘贴",
    右键菜单里却是勾上的。
    """
    cfg = Config()
    cfg.ui.badge_action = "paste_and_send"
    pal = apply_theme(qapp, "dark")

    tray = Tray(pal)
    tray.apply(cfg)
    win = MainWindow(cfg, pal, None)

    assert tray._act_send.isChecked()
    assert win.general.badge_action.currentData() == "paste_and_send"
    win.deleteLater()


# ---- 点一下之后到底做了什么 ----


class FakeSession:
    def __init__(self, recording: bool) -> None:
        self.is_recording = recording
        self.finished_with: str | None = None

    def finish(self, action: str) -> None:
        self.finished_with = action


class FakeApp:
    """只带这条路径所需字段的替身,复用 App 上的真实方法。"""

    def __init__(self, action: str, recording: bool) -> None:
        self.session = FakeSession(recording)
        self.started_with: str | None = None
        self._cfg = Config()
        self._cfg.ui.badge_action = action

    @property
    def cfg(self) -> Config:
        return self._cfg

    def _begin_recording(self, action: str) -> None:
        self.started_with = action

    _toggle_from_badge = App._toggle_from_badge


@pytest.mark.parametrize("action", ["paste", "paste_and_send"])
def test_开始录音时就带上了配置里的动作(action):
    app = FakeApp(action, recording=False)
    app._toggle_from_badge()
    assert app.started_with == action


@pytest.mark.parametrize("action", ["paste", "paste_and_send"])
def test_结束录音时也带上同一个动作(action):
    """开始和结束必须一致 —— 只改一处的话,勾了"直接发送"却还是不发。"""
    app = FakeApp(action, recording=True)
    app._toggle_from_badge()
    assert app.session.finished_with == action
