"""向导第一步:说清楚这个工具是干什么的。

这一步没有任何状态,也不写配置。
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel

from ..theme import Palette
from ..widgets import Card, hint
from .base import Step


class WelcomeStep(Step):
    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__("欢迎使用 VoiceInput", parent)
        self.body.addWidget(hint(
            "按住热键说话,松开后文字直接出现在当前光标处。\n"
            "识别全程在本机完成,音频不会上传到任何地方。"
        ))

        card = Card("这个向导会带你做三件事")
        for num, text in [
            ("1", "准备语音识别模型(约 160 MB,只需一次)"),
            ("2", "标定麦克风 —— 会真的录一句话跑一遍识别,确认选对了设备"),
            ("3", "设置热键 —— 会当场探测有没有被别的程序占用"),
        ]:
            row = QHBoxLayout()
            badge = QLabel(num)
            badge.setFixedWidth(20)
            badge.setStyleSheet(f"color: {palette.accent}; font-weight: 700;")
            body = QLabel(text)
            body.setWordWrap(True)
            row.addWidget(badge)
            row.addWidget(body, 1)
            card.add_layout(row)
        self.body.addWidget(card)

        self.body.addWidget(hint("全部可以之后在设置里改。随时可以点左下角跳过。"))
        self.body.addStretch(1)
