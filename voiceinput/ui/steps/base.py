"""向导每一步的公共骨架。

**这里只放"每一步都一样"的东西。** 一旦出现 if 判断"这是第几步",
就说明拆错了。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...config import Config


class Step(QWidget):
    """向导的一步:自己拥有自己的控件,自己知道怎么写回 Config。

    这是拆分的边界。向导本身不认识任何一个具体控件,它只知道
    "有若干个 Step,每个都能 on_enter / apply_to / summary_rows"。
    """

    busyChanged = Signal(bool)
    """这一步正在做不能被打断的事(比如下载模型),导航按钮要跟着禁用。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(14)
        if title:
            label = QLabel(title)
            label.setProperty("role", "title")
            self.body.addWidget(label)

    # ---- 子类按需覆盖 ----

    def on_enter(self) -> None:
        """翻到这一步了。"""

    def on_leave(self) -> None:
        """翻走了。占着设备/线程的要在这里放开。"""

    def apply_to(self, cfg: Config) -> None:
        """把这一步的选择写进 cfg。"""

    def summary_rows(self) -> list[tuple[str, str]]:
        """最后一页的摘要里,这一步该贡献哪几行。

        **由拥有这个设置的步骤自己回答** —— 让最后一页去各处翻别人的字段,
        改了任何一步都得记得回来改它。
        """
        return []

    def shutdown(self) -> None:
        """向导关掉了。线程之类的收摊在这里做。"""
