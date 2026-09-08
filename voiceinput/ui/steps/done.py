"""向导最后一步:把前面几步的选择摊开给用户过目。

摘要的每一行**由拥有那个设置的步骤自己提供**(`Step.summary_rows()`)。
这里只负责摆出来 —— 让这一页去各处翻别人的字段的话,
改了任何一步都得记得回来改它。
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel

from ...config import Config
from ..widgets import Card, hint
from .base import Step


class DoneStep(Step):
    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__("设置完成", parent)

        self.summary = Card("你的配置")
        self.body.addWidget(self.summary)

        self.autostart = QCheckBox("开机自动启动")
        self.autostart.setChecked(cfg.autostart)
        self.body.addWidget(self.autostart)
        self.body.addWidget(hint(
            "自启是往启动文件夹放一个快捷方式,不写注册表。\n\n"
            "程序会常驻在系统托盘。双击托盘图标可以随时打开设置、查看识别历史,"
            "或者重新运行这个向导。"
        ))
        self.body.addStretch(1)

    def fill(self, rows: list[tuple[str, str]]) -> None:
        # 每次进这一页都重建,免得来回翻页时显示的是旧值
        while self.summary.body.count():
            item = self.summary.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for label, value in rows:
            row = QHBoxLayout()
            left = QLabel(label)
            left.setFixedWidth(96)
            left.setProperty("role", "hint")
            right = QLabel(value)
            right.setWordWrap(True)
            row.addWidget(left)
            row.addWidget(right, 1)
            self.summary.add_layout(row)

    def apply_to(self, cfg: Config) -> None:
        cfg.autostart = self.autostart.isChecked()
