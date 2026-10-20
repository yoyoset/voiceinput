"""系统托盘。程序常驻的入口——主窗口关掉之后,这里是唯一的可见部分。

这里的菜单**同时也是悬浮麦克风的右键菜单**(`MicBadge.set_menu`)。
只建一份是有意的:两份菜单会漂移成不一样的选项,而没人会发现。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..config import Config
from .icons import state_icon
from .theme import Palette


class Tray(QSystemTrayIcon):
    openRequested = Signal()
    historyRequested = Signal()
    quitRequested = Signal()
    pauseToggled = Signal(bool)
    wizardRequested = Signal()
    sendAfterChanged = Signal(bool)
    """「说完直接发送」被勾上/取消。真正的存储在 `cfg.ui.badge_action`。"""

    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._state = "loading"

        menu = QMenu()
        self._act_status = QAction("正在启动…", menu)
        self._act_status.setEnabled(False)
        menu.addAction(self._act_status)
        menu.addSeparator()

        # 放在最上面:要找刚才没粘进去的那句话时最急,不该先进设置翻选项卡
        act_history = QAction("历史记录", menu)
        act_history.triggered.connect(self.historyRequested.emit)
        menu.addAction(act_history)

        act_open = QAction("设置与历史", menu)
        act_open.triggered.connect(self.openRequested.emit)
        menu.addAction(act_open)

        act_wizard = QAction("重新运行向导", menu)
        act_wizard.triggered.connect(self.wizardRequested.emit)
        menu.addAction(act_wizard)

        # 放在这里而不是只放设置页里:用的时候人就在悬浮麦克风上,
        # 「这一句要不要直接发出去」是个随时会变的决定,不该逼人去翻设置。
        self._act_send = QAction("点一下说完直接发送", menu)
        self._act_send.setCheckable(True)
        self._act_send.setToolTip("说完自动补一个回车。发出去就撤不回来了,识别错也一样。")
        self._act_send.toggled.connect(self.sendAfterChanged.emit)
        menu.addAction(self._act_send)

        self._act_pause = QAction("暂停监听", menu)
        self._act_pause.setCheckable(True)
        self._act_pause.toggled.connect(self.pauseToggled.emit)
        menu.addAction(self._act_pause)

        menu.addSeparator()
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quitRequested.emit)
        menu.addAction(act_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.set_state("loading", "正在启动…")

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.openRequested.emit()

    def apply(self, cfg: Config) -> None:
        """配置变了,菜单上的勾要跟着走。

        **必须挡住信号。** 不挡的话,设置页改了这一项 → 配置分发到这里 →
        勾一变又发一次 sendAfterChanged → 又写一次配置,绕成一个环。
        """
        want = cfg.ui.badge_action == "paste_and_send"
        if want == self._act_send.isChecked():
            return
        blocked = self._act_send.blockSignals(True)
        self._act_send.setChecked(want)
        self._act_send.blockSignals(blocked)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.set_state(self._state, self._act_status.text())

    def set_state(self, state: str, text: str) -> None:
        self._state = state
        p = self._palette
        self.setIcon(state_icon(state, p.accent, p.danger, p.text_dim))
        self._act_status.setText(text)
        self.setToolTip(f"VoiceInput — {text}")

    @property
    def is_paused(self) -> bool:
        return self._act_pause.isChecked()
