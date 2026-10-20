"""悬浮麦克风。

存在的理由:托盘图标太小、平时看不出程序是否活着;更要紧的是
**全局热键会和别的软件撞**(实测和微信撞过),撞上之后没有别的入口。
这个按钮就是那条退路 —— 它完全不依赖热键。
"""

import pytest

from PySide6.QtCore import QPoint, Qt

from voiceinput.ui import theme
from voiceinput.ui.mic_badge import SIZE, MicBadge


@pytest.fixture
def badge(qapp):
    b = MicBadge(theme.DARK)
    # 巡检里两个直接调 Win32 的,测试里不能碰真桌面
    b._covering = lambda hwnd: None
    b._lift = lambda hwnd: True
    yield b
    b.close()


class TestFocusBehaviour:
    def test_does_not_accept_focus(self, badge):
        """**最关键的一条。**

        点它的时候,你正在打字的那个窗口必须保持焦点 ——
        否则识别完的文字会粘到别处去,而不是你要的地方。
        """
        assert badge.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus

    def test_shows_without_activating(self, badge):
        assert badge.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def test_stays_on_top(self, badge):
        """被别的窗口盖住就失去意义了。"""
        assert badge.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


class TestStates:
    @pytest.mark.parametrize(
        "state", ["idle", "recording", "busy", "error", "loading", "paused"])
    def test_all_states_render(self, badge, state):
        badge.set_state(state)
        assert not badge.grab().isNull()

    def test_recording_animates(self, badge):
        """静止和动起来本身就是状态 —— 不动的话看不出在不在听。"""
        badge.set_state("recording")
        assert badge._anim.isActive()

    def test_idle_does_not_animate(self, badge):
        """平时别一直重绘,白耗电。"""
        badge.set_state("recording")
        badge.set_state("idle")
        assert not badge._anim.isActive()

    def test_level_resets_when_leaving_recording(self, badge):
        badge.set_state("recording")
        badge.set_level(-20.0)
        badge.set_state("idle")
        assert badge._level == 0.0


class TestLevel:
    def test_silence_is_zero(self, badge):
        badge.set_level(float("-inf"))
        assert badge._level == 0.0

    def test_loud_is_full(self, badge):
        badge.set_level(0.0)
        assert badge._level == 1.0

    def test_quiet_is_low(self, badge):
        badge.set_level(-55.0)
        assert badge._level < 0.2


class TestPositioning:
    def test_clamped_into_screen(self, badge):
        """换显示器或改分辨率之后,存下来的坐标可能已经在屏幕外 ——
        那样按钮就永远看不见了。"""
        badge.move_to(999_999, 999_999)
        from PySide6.QtWidgets import QApplication

        area = QApplication.primaryScreen().availableGeometry()
        assert badge.x() <= area.right() - SIZE
        assert badge.y() <= area.bottom() - SIZE

    def test_negative_clamped(self, badge):
        badge.move_to(-500, -500)
        assert badge.x() >= 0 and badge.y() >= 0

    def test_default_position_is_on_screen(self, badge):
        from PySide6.QtWidgets import QApplication

        badge.move_to_default()
        area = QApplication.primaryScreen().availableGeometry()
        assert area.contains(QPoint(badge.x(), badge.y()))


class TestClickVsDrag:
    """点击要能触发录音,拖动不能 —— 拖完手一松就开始录音会很烦。"""

    def press(self, badge, x, y):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        for kind, handler in [(QEvent.Type.MouseButtonPress, badge.mousePressEvent)]:
            handler(QMouseEvent(kind, QPointF(0, 0), QPointF(x, y),
                                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier))

    def move(self, badge, x, y):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        badge.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, QPointF(0, 0), QPointF(x, y),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))

    def release(self, badge, x, y):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        badge.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(0, 0), QPointF(x, y),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))

    def test_click_emits_clicked(self, badge):
        clicks = []
        badge.clicked.connect(lambda: clicks.append(True))
        badge.move_to(300, 300)
        self.press(badge, 320, 320)
        self.release(badge, 320, 320)
        assert clicks == [True]

    def test_drag_emits_moved_not_clicked(self, badge):
        clicks, moves = [], []
        badge.clicked.connect(lambda: clicks.append(True))
        badge.moved.connect(lambda x, y: moves.append((x, y)))
        badge.move_to(300, 300)
        self.press(badge, 320, 320)
        self.move(badge, 500, 500)
        self.release(badge, 500, 500)
        assert clicks == [], "拖动不该触发录音"
        assert len(moves) == 1

    def test_tiny_jitter_is_still_a_click(self, badge):
        """按下时手抖两像素,应该仍然算点击。"""
        clicks = []
        badge.clicked.connect(lambda: clicks.append(True))
        badge.move_to(300, 300)
        self.press(badge, 320, 320)
        self.move(badge, 321, 321)
        self.release(badge, 321, 321)
        assert clicks == [True]


class TestGuard:
    """被系统从外面藏掉之后要自己回来 —— 2026-09-24 的故障是只能取消再勾上。"""

    def test_guard_runs_only_while_wanted(self, badge):
        badge.show()
        assert badge._guard.isActive()
        badge.hide()
        assert not badge._guard.isActive()

    def test_hidden_by_system_gets_reshown(self, badge, monkeypatch):
        badge.show()
        badge._probe = lambda hwnd: (False, False, 0)   # Windows 说:看不见
        reshown = []
        monkeypatch.setattr(badge, "_reshow", lambda: reshown.append(1))
        badge._guard_check()
        assert reshown == [1]
        assert badge._last_problems == ["被隐藏"]

    def test_healthy_window_is_left_alone(self, badge, monkeypatch):
        badge.show()
        badge.move_to_default()
        badge._probe = lambda hwnd: (True, False, 0)
        reshown = []
        monkeypatch.setattr(badge, "_reshow", lambda: reshown.append(1))
        badge._guard_check()
        assert reshown == []

    def test_not_wanted_means_no_check(self, badge, monkeypatch):
        """用户自己关掉的,不能被巡检又弄出来。"""
        badge.hide()
        badge._probe = lambda hwnd: (False, False, 0)
        reshown = []
        monkeypatch.setattr(badge, "_reshow", lambda: reshown.append(1))
        badge._guard_check()
        assert reshown == []

    def test_covered_by_normal_window_is_lifted_not_reshown(self, badge, monkeypatch):
        """**2026-10-20 现场。** 窗口本身好好的,只是沉到了普通窗口下面:
        重新插回置顶档就够了,不要 hide → show(会闪一下)。"""
        badge.show()
        badge.move_to_default()
        badge._probe = lambda hwnd: (True, False, 0)
        badge._covering = lambda hwnd: "chrome.exe:Chrome_WidgetWin_1"
        lifted, reshown = [], []
        badge._lift = lambda hwnd: lifted.append(hwnd)
        monkeypatch.setattr(badge, "_reshow", lambda: reshown.append(1))
        badge._guard_check()
        assert lifted == [int(badge.winId())]
        assert reshown == []
        assert badge._last_problems == ["被普通窗口压在下面(chrome.exe:Chrome_WidgetWin_1)"]

    def test_hidden_window_is_not_asked_about_z_order(self, badge, monkeypatch):
        """窗口都不在了就先摆出来;这时候查 z 序没有意义,也不该再置顶一次。"""
        badge.show()
        badge._probe = lambda hwnd: (False, False, 0)
        asked, lifted = [], []
        badge._covering = lambda hwnd: asked.append(hwnd)
        badge._lift = lambda hwnd: lifted.append(hwnd)
        monkeypatch.setattr(badge, "_reshow", lambda: None)
        badge._guard_check()
        assert asked == [] and lifted == []

    def test_healthy_window_is_not_lifted(self, badge, monkeypatch):
        """没被压住时不能每 3 秒都重设置顶 —— 会和别的置顶程序(magpie、画中画)抢。"""
        badge.show()
        badge.move_to_default()
        badge._probe = lambda hwnd: (True, False, 0)
        lifted = []
        badge._lift = lambda hwnd: lifted.append(hwnd)
        badge._guard_check()
        assert lifted == []
