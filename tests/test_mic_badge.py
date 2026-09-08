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
