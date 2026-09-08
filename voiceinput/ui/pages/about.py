"""「关于」页:程序在磁盘上留下的每一样东西,配一个能打开它的按钮。

出问题时这里是用户唯一能自助的地方,所以路径必须列全 ——
"删掉即卸载"这句话只有在列全了的前提下才是真的。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton

from ... import autostart as autostart_mod
from ...config import Config, app_dir
from ..widgets import Card, hint
from .base import Page


class AboutPage(Page):
    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)

        card = Card("VoiceInput")
        card.add(hint(
            "按住热键说话,松开后文字直接出现在光标处。\n"
            "识别全程在本机完成,音频不上传。"
        ))
        for label, value in self._footprint():
            row = QLabel(f"{label}:{value}")
            row.setProperty("role", "mono")
            row.setWordWrap(True)
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card.add(row)

        # 出问题时最该看的就是日志,但让用户自己按路径去翻等于没给。
        # 打包成 exe 之后程序目录可能在任何地方,更找不着。
        acts = QHBoxLayout()
        btn_log = QPushButton("打开日志")
        btn_log.clicked.connect(self.open_log)
        btn_dir = QPushButton("打开程序目录")
        btn_dir.clicked.connect(lambda: self._reveal(app_dir()))
        acts.addWidget(btn_log)
        acts.addWidget(btn_dir)
        acts.addStretch(1)
        card.add_layout(acts)

        card.add(hint(
            "绿色软件:配置和历史都放在程序目录旁边,不写注册表、不写 AppData。"
            "整个目录拷走即可换机器使用。\n\n"
            "彻底卸载 = 删掉程序目录 + 删掉上面那个自启快捷方式(如果启用过)。"
            "后者是唯一在程序目录之外的东西。"
        ))
        self.body.addWidget(card)
        self.body.addStretch(1)

    @staticmethod
    def _footprint() -> list[tuple[str, str]]:
        return [
            ("程序目录", str(app_dir())),
            ("配置文件", str(app_dir() / "config.toml")),
            ("历史数据库", str(app_dir() / "history.db")),
            ("日志", str(app_dir() / "voiceinput.log")),
            ("自启快捷方式", str(autostart_mod.shortcut_path())),
        ]

    def open_log(self) -> None:
        """用系统默认程序打开日志。日志还没生成时说清楚,别静默什么都不发生。"""
        log = app_dir() / "voiceinput.log"
        if not log.exists():
            QMessageBox.information(
                self, "日志",
                f"日志文件还没生成:\n{log}\n\n程序运行一会儿后才会有内容。")
            return
        self._reveal(log)

    @staticmethod
    def _reveal(path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def collect(self, cfg: Config) -> None:
        """这一页没有任何可改的设置。"""
