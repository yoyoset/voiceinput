"""通用小控件。"""

from __future__ import annotations

from PySide6.QtCore import Property, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from .theme import Palette


class WheelGuard:
    """滚轮不改值,除非这个控件自己拿着焦点。

    设置页是可滚动的,而 Qt 默认把滚轮交给鼠标底下的控件。于是**滚一下页面,
    路过的每一个控件都被顺手改掉了**:「触发方式」从"按住说话"变成"按一下切换"、
    「麦克风」换成另一个设备、「线程数」变了还顺带触发一次三秒的模型重载。

    这一切**不报任何错、界面也不会跳回去**,用户滚过去就什么都不知道了 ——
    正是这个项目最该排除的那类失败。

    加了焦点判断之后,想用滚轮调值仍然可以:先点一下那个控件。
    """

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
            return
        # **不能只 ignore() 了事。** 那是指望 Qt 自己把事件往上传给滚动区域,
        # 而这条路走不走得通取决于 Qt 版本和事件是怎么投递进来的 ——
        # 赌错的代价是"鼠标停在控件上整个页面就滚不动了",修一个坏一个。
        # 这里自己找到那个滚动区域,把事件明确交过去。
        area = self._scroll_area()
        if area is None:
            event.ignore()
            return
        QApplication.sendEvent(area.viewport(), event)

    def _scroll_area(self) -> QAbstractScrollArea | None:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                return parent
            parent = parent.parentWidget()
        return None


class SelfDrawnArrow:
    """自己画箭头的控件。

    Qt 样式表画箭头**必须给图片资源**,而这是个绿色软件,不想带资源文件。
    不画又不行:样式表一旦接管了下拉框/数字框,Qt 自带的箭头要么跟着消失
    (下拉框看起来就是个只读文本框),要么保持系统原生的浅色方块 ——
    深色主题里那两个方块亮得像是外来的、坏掉的东西。

    颜色走 `qproperty-arrowColor`,主题切换时样式表直接改它,
    不用在代码里逐个控件更新。
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._arrow_color = QColor("#94A69B")

    def get_arrow_color(self) -> QColor:
        return self._arrow_color

    def set_arrow_color(self, color: QColor) -> None:
        self._arrow_color = QColor(color)
        self.update()

    arrowColor = Property(QColor, get_arrow_color, set_arrow_color)

    def _chevron(self, painter: QPainter, cx: float, cy: float,
                 up: bool = False) -> None:
        pen = QPen(self._arrow_color)
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        half, dy = 4.0, -2.0 if up else 2.0
        path = QPainterPath()
        path.moveTo(cx - half, cy - dy)
        path.lineTo(cx, cy + dy)
        path.lineTo(cx + half, cy - dy)
        painter.drawPath(path)


class _Stepper(SelfDrawnArrow, WheelGuard):
    """数字框右侧那对上下箭头。

    **位置必须问 QStyle 要,不能自己按 width 算。** 样式表改一次 padding
    就会挪动按钮,写死的坐标当场对不上 —— 而箭头画歪了不报错,
    只是点上去没反应,看起来就跟控件坏了一样。
    """

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        opt = QStyleOptionSpinBox()
        opt.initFrom(self)
        opt.rect = self.rect()
        opt.subControls = QStyle.SubControl.SC_All
        style = self.style()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for sub, up in ((QStyle.SubControl.SC_SpinBoxUp, True),
                        (QStyle.SubControl.SC_SpinBoxDown, False)):
            r = style.subControlRect(QStyle.ComplexControl.CC_SpinBox, opt, sub, self)
            self._chevron(painter, r.center().x() + 0.5, r.center().y() + 0.5, up)
        painter.end()


class SpinBox(_Stepper, QSpinBox):
    pass


class DoubleSpinBox(_Stepper, QDoubleSpinBox):
    pass


class ComboBox(SelfDrawnArrow, WheelGuard, QComboBox):
    """带下拉箭头的 QComboBox。"""

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._chevron(painter, self.width() - 15.0, self.height() / 2.0)
        painter.end()


class FloatingHud:
    """不抢焦点、常驻最前的浮动小窗口共用的样板。

    悬浮麦克风(`MicBadge`)和悬浮提示条(`Overlay`)是同一类东西:按下热键
    的瞬间不能抢焦点(否则当前输入框失焦,粘贴就粘错地方了)、要一直盖在
    最上面、背景得透明。这段 Qt 窗口标志位以前在两处各写一遍——**这类
    底层设置最怕漂移**:改一处忘了改另一处,表现是"某天这个窗口开始
    抢焦点了",不会报任何错,只会在真实使用时才被人发现。

    两者唯一的差异是窗口类型(`Tool` / `ToolTip`)和固定尺寸,由子类
    在 `_init_floating` 里传进来。
    """

    def _init_floating(self, palette: Palette, window_type: Qt.WindowType,
                       size: tuple[int, int], parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            window_type
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(*size)
        self._palette = palette

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()


class Card(QFrame):
    """带边框的分组容器。"""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setProperty("role", "section")
            outer.addWidget(label)
        self.body = QVBoxLayout()
        self.body.setSpacing(9)
        outer.addLayout(self.body)

    def add(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)


class LevelBar(QWidget):
    """麦克风电平表。

    刻度不是线性的 0-100%,是 dBFS:-60 当静音,-10 当满格。
    并且要标出 -50 dBFS 这条"疑似没录到人声"的线,
    否则用户看到一点点绿色也会以为设备选对了。
    """

    SILENCE_DBFS = -50.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._level = float("-inf")
        self._accent = "#22C55E"
        self._danger = "#F87171"
        self._track = "#2E3A32"
        self._border = "#2E3A32"

    def set_colors(self, accent: str, danger: str, track: str, border: str) -> None:
        self._accent, self._danger = accent, danger
        self._track, self._border = track, border
        self.update()

    def set_level(self, dbfs: float) -> None:
        self._level = dbfs
        self.update()

    @property
    def is_silent(self) -> bool:
        return self._level < self.SILENCE_DBFS

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bar_h = 12.0
        y = (h - bar_h) / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._track))
        painter.drawRoundedRect(0, y, w, bar_h, 6, 6)

        if self._level != float("-inf"):
            frac = max(0.0, min(1.0, (self._level + 60.0) / 50.0))
            if frac > 0:
                color = self._accent if not self.is_silent else self._danger
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(0, y, max(4.0, w * frac), bar_h, 6, 6)

        # -50 dBFS 分界线
        mark = (self.SILENCE_DBFS + 60.0) / 50.0
        painter.setPen(QColor(self._border))
        x = w * mark
        painter.drawLine(int(x), int(y - 3), int(x), int(y + bar_h + 3))
        painter.end()


def row(*widgets: QWidget, stretch_last: bool = False) -> QHBoxLayout:
    """把若干控件排成一行。"""
    layout = QHBoxLayout()
    layout.setSpacing(9)
    for i, wdg in enumerate(widgets):
        layout.addWidget(wdg)
        if stretch_last and i == len(widgets) - 1:
            layout.setStretchFactor(wdg, 1)
    return layout


def labeled(text: str, widget: QWidget, width: int = 108) -> QHBoxLayout:
    """左边固定宽度的标签 + 右边控件,让各行标签对齐。"""
    layout = QHBoxLayout()
    layout.setSpacing(9)
    label = QLabel(text)
    label.setFixedWidth(width)
    layout.addWidget(label)
    layout.addWidget(widget, 1)
    return layout


def hint(text: str) -> QLabel:
    """说明文字。`**这样**` 会变成粗体。

    加这个不是为了排版好看,是因为**文案里已经写着 markdown 了** ——
    这些句子当初就是照着文档的写法敲的,而 QLabel 默认按纯文本显示,
    于是界面上原样出现两个星号:「这类名字通常是\\*\\*系统声音回环\\*\\*」。
    与其挨个把星号删掉(下次写文案的人还会再写),不如让它真的生效。
    """
    label = QLabel(_bold(text))
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


def _bold(text: str) -> str:
    """`**x**` -> `<b>x</b>`。**先转义再替换**,否则文案里的 `<` 会被当成标签。"""
    import html
    import re

    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>",
                  html.escape(text)).replace("\n", "<br>")


def spin(lo: int, hi: int, value: int, suffix: str = "", step: int = 1) -> SpinBox:
    """一个数字框。**`step` 要按这个值本身的量级给,不能留默认的 1。**

    实测出来的教训:所有数字框都是默认步长 1,而框里放的是 80 毫秒、
    1200 毫秒、2000 条 —— 点一下箭头 2000 变成 2001,看上去跟没反应一样,
    用户的原话是"上下调整数值的这个是不能用的"。

    取值大致按"一次点击走完整个范围的百分之一到二"来定。
    """
    box = SpinBox()
    box.setRange(lo, hi)
    box.setSingleStep(step)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


def wrap(layout) -> QWidget:
    """把一个 layout 塞进 QWidget —— `labeled()` 只收控件不收 layout。"""
    holder = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    holder.setLayout(layout)
    return holder


def restyle(widget: QWidget) -> None:
    """改了 property 之后要让样式表重新生效,否则 role 换了颜色不变。"""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
