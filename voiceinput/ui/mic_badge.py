"""常驻桌面的悬浮麦克风。

**为什么需要它**,而不是只有录音时才弹的提示条:

1. **平时也要有存在感。** 托盘图标太小、容易被折叠起来,用户不确定程序是不是活着。
2. **给热键一条退路。** 全局热键会和别的软件撞(实测和微信撞过),
   撞上了就没法用 —— 有个能点的按钮,不改热键也能说话。
3. **反馈要在视线里。** 录音时的电平变化画在按钮上,一眼就知道"它在听"。

两个必须守住的点:

- **不能抢焦点。** 点它的时候,你正在打字的那个窗口必须保持焦点,
  否则识别完的文字会粘到别处去。靠 `WindowDoesNotAcceptFocus` +
  `WA_ShowWithoutActivating`,鼠标事件照收,焦点不动。
- **要能拖走。** 固定在角落必然挡住某些人的东西,位置存进配置。
- **右键要出菜单。** 桌面上一个圆按钮,出了问题第一反应就是右键点它 ——
  以前右键什么都不发生,于是唯一的出路是去托盘里找那个很小的图标。
  菜单直接用托盘那一份,不另写:两份菜单迟早会漂移成不一样的。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .theme import Palette
from .widgets import FloatingHud

SIZE = 60
_DRAG_THRESHOLD = 4      # 小于这个位移算点击,不算拖动


def _stroke(color: QColor, width: float) -> QPen:
    """描边用的画笔。

    **必须新建,不能拿 `painter.pen()` 改**:setPen(NoPen) 之后取回来的
    还是 NoPen 样式,只改颜色宽度依然什么都画不出来。
    """
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


class MicBadge(FloatingHud, QWidget):
    """一个可拖动、可点击的悬浮麦克风。"""

    clicked = Signal()
    moved = Signal(int, int)     # 拖完之后的新位置,交给上层存配置

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        self._init_floating(palette, Qt.WindowType.Tool, (SIZE, SIZE), parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点一下开始说话,再点一下结束")

        self._state = "idle"
        self._level = 0.0
        self._pulse = 0.0
        self._hover = False
        self._press_pos: QPoint | None = None
        self._dragged = False
        self._menu: QMenu | None = None

        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick)

    # ---- 对外 ----

    def set_menu(self, menu: QMenu) -> None:
        """右键菜单。**传托盘那一份进来,不要在这里另建一个。**

        两份菜单会漂移:改了托盘那份忘了改这份,于是同一个程序右键点
        托盘和右键点悬浮麦克风给出的选项不一样,而且没人会发现。
        """
        self._menu = menu

    def set_state(self, state: str) -> None:
        """idle / recording / busy / error / loading / paused"""
        if state == self._state:
            return
        self._state = state
        if state in ("recording", "busy"):
            self._anim.start(50)
        else:
            self._anim.stop()
            self._level = 0.0
        self.update()

    def set_level(self, dbfs: float) -> None:
        """录音电平,画成外圈。-60 当静音,-10 当满格。"""
        level = 0.0 if dbfs == float("-inf") else max(0.0, min(1.0, (dbfs + 60.0) / 50.0))
        if abs(level - self._level) > 0.01:
            self._level = level
            self.update()

    def move_to(self, x: int, y: int) -> None:
        """挪到指定位置,并夹在屏幕内 —— 换了分辨率或拔了外接屏之后,
        存下来的坐标可能已经在屏幕外,那样按钮就永远看不见了。"""
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - SIZE))
            y = max(area.top(), min(y, area.bottom() - SIZE))
        self.move(x, y)

    def move_to_default(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move_to(area.right() - SIZE - 28, area.bottom() - SIZE - 120)

    # ---- 交互 ----

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """右键。**用 exec 而不是 popup** —— popup 之后函数立刻返回,
        而这个窗口是 `WindowDoesNotAcceptFocus` 的,菜单会当场失去激活
        然后自己关掉,表现为"右键闪一下什么都没有"。
        """
        if self._menu is None:
            return
        self._menu.exec(event.globalPos())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint() - self.pos()
            self._dragged = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_pos is None:
            return
        target = event.globalPosition().toPoint() - self._press_pos
        if not self._dragged:
            moved = (target - self.pos()).manhattanLength()
            if moved < _DRAG_THRESHOLD:
                return          # 手抖不算拖动,否则点一下就变成了微小位移
            self._dragged = True
        self.move_to(target.x(), target.y())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._press_pos is None:
            return
        self._press_pos = None
        if self._dragged:
            self.moved.emit(self.x(), self.y())
        else:
            self.clicked.emit()

    # ---- 绘制 ----

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.06) % 1.0
        # **必须是 `repaint()`,不能是 `update()`。** 后者只是排队等下一轮
        # 事件循环来画,而这个窗口置顶、透明背景、不抢焦点——实测在这种
        # 组合下 Windows 偶尔会把排队的这次重画请求吞掉,画面停在原地不动,
        # 直到别的操作(拖动、切窗口)强制系统整个重新合成一遍才恢复。
        # 动画每 50 毫秒跳一次,吞一次就是一次卡住,`repaint()` 立即同步画,
        # 不给它排队的机会。
        self.repaint()

    def _color(self) -> QColor:
        p = self._palette
        return QColor({
            "recording": p.accent,
            "busy": p.warning,
            "error": p.danger,
            "loading": p.text_dim,
            "paused": p.text_dim,
        }.get(self._state, p.accent))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._color()
        cx = cy = SIZE / 2

        # 录音时的电平外圈 —— 这是"它真的听到了"最直接的证据
        if self._state == "recording" and self._level > 0:
            ring = QColor(c)
            ring.setAlpha(90)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ring)
            r = SIZE / 2 * (0.82 + 0.18 * self._level)
            painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # 识别中:转一圈,表示还在忙而不是卡死
        if self._state == "busy":
            # 必须新建 QPen。`painter.pen()` 在 setPen(NoPen) 之后拿回来的
            # 仍然是 NoPen 样式,只改颜色和宽度画不出任何东西 ——
            # 这个坑让话筒的托架和支柱一开始整个是隐形的。
            painter.setPen(_stroke(c, 3.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            span = 100 * 16
            start = int(-self._pulse * 360 * 16)
            painter.drawArc(QRectF(5, 5, SIZE - 10, SIZE - 10), start, span)

        # 主体圆盘
        body = QColor(p.surface)
        body.setAlpha(238 if self._hover or self._state != "idle" else 214)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(body)
        d = SIZE * 0.78
        painter.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))

        edge = QColor(c)
        edge.setAlpha(255 if self._state != "idle" else (200 if self._hover else 130))
        painter.setPen(_stroke(edge, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))

        # 话筒图形。录音时随呼吸微微放大,静止时不动 —— 动静本身就是状态。
        scale = 1.0 + (0.08 * math.sin(self._pulse * 2 * math.pi)
                       if self._state == "recording" else 0.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        w = SIZE * 0.16 * scale
        h = SIZE * 0.30 * scale
        painter.drawRoundedRect(
            QRectF(cx - w / 2, cy - h * 0.75, w, h), w / 2, w / 2)

        painter.setPen(_stroke(c, 2.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arc_w = SIZE * 0.30 * scale
        arc_h = SIZE * 0.26 * scale
        painter.drawArc(
            QRectF(cx - arc_w / 2, cy - arc_h * 0.35, arc_w, arc_h), 200 * 16, 140 * 16)
        painter.drawLine(int(cx), int(cy + arc_h * 0.6), int(cx), int(cy + arc_h * 0.95))

        # 暂停时打一道斜杠,和"就绪"明确区分开
        if self._state == "paused":
            painter.setPen(_stroke(c, 2.6))
            painter.drawLine(int(cx - d * 0.28), int(cy + d * 0.28),
                             int(cx + d * 0.28), int(cy - d * 0.28))
        painter.end()
