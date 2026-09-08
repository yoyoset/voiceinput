"""设置分页的公共骨架。

**这里只放"所有分页都一样"的东西**,任何一个分页特有的逻辑都不该进来 ——
这个文件一旦开始出现 if 判断"是哪一页",就说明拆错了。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from ...config import Config


class Page(QWidget):
    """一个分页:自己拥有自己的控件,自己知道怎么写回 Config。

    这是拆分的边界所在。窗口不认识任何一个具体控件,它只知道
    "有若干个 Page,每个都会 changed,每个都能 collect"。
    """

    changed = Signal()

    def __init__(self, scroll: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(4, 12, 4, 4)
        self.body.setSpacing(12)

        if not scroll:
            # 表格自己会滚,再套一层滚动区域会出现两根滚动条
            outer.addWidget(inner)
            return

        # 不套滚动区域的话,内容一旦超出窗口高度,Qt 会把各行**压扁**去凑合 ——
        # 下拉框的文字被切成一半那种。触发条件很容易达到:热键那栏多出
        # 两行冲突警告就够了,更别说小屏幕或放大的系统字体。
        area = QScrollArea()
        area.setWidget(inner)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(area)

    # ---- 子类用 ----

    def emit_changed(self, *_) -> None:
        """界面被改动了。初始化填值期间(`_loading`)不算。"""
        if not self._loading:
            self.changed.emit()

    def collect(self, cfg: Config) -> None:
        """把界面上的值写回 cfg。子类必须实现。"""
        raise NotImplementedError
