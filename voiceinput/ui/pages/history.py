"""「历史」页:只剩记录设置和一个入口。

**原来这里有一整套表格 + 预览 + 粘贴/复制/删除按钮,已经去掉。**
它挤在设置窗口里,表格只露得出一行半,用户原话"根本看不见,没办法去选"。
找回说过的话改到独立的历史窗口(`ui/history_window.py`),托盘和悬浮
麦克风右键都能直接打开。同一份历史保留两套浏览界面,迟早改一边忘一边。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QMessageBox, QPushButton

from ...config import Config
from ..widgets import Card, hint, labeled, row, spin
from .base import Page


class HistoryPage(Page):
    openWindowRequested = Signal()

    def __init__(self, cfg: Config, history, parent=None) -> None:
        super().__init__(scroll=False, parent=parent)
        self._history = history

        card = Card("识别历史")
        card.add(hint(
            "说过的每一句话都会记下来。没粘进去、粘错了地方,去历史记录里找回来,不用重说。\n"
            "**打开方式**:右键悬浮麦克风或托盘图标 →「历史记录」,或者点下面的按钮。"
        ))
        self.btn_window = QPushButton("打开历史记录")
        self.btn_window.setProperty("role", "primary")
        self.btn_window.clicked.connect(self.openWindowRequested.emit)
        self.count_label = QLabel("")
        self.count_label.setProperty("role", "hint")
        card.add_layout(row(self.btn_window, self.count_label, stretch_last=True))
        self.body.addWidget(card)

        # 这两个开关本来只存在于 config.toml 里,界面上完全没有 ——
        # 等于"想关掉得先知道有个配置文件"。
        opts = Card("记录设置")
        self.hist_enabled = QCheckBox("记录识别历史")
        self.hist_enabled.setChecked(cfg.history.enabled)
        self.hist_enabled.toggled.connect(self._on_toggled)
        opts.add(self.hist_enabled)

        self.hist_max = spin(50, 100_000, cfg.history.max_entries, " 条", step=100)
        self.hist_max.setEnabled(cfg.history.enabled)
        self.hist_max.valueChanged.connect(self.emit_changed)
        opts.add_layout(labeled("最多保留", self.hist_max))
        opts.add(hint("超出后自动删最旧的。关掉记录不会删已有的。"))

        btn_clear = QPushButton("清空全部历史")
        btn_clear.setProperty("role", "danger")
        btn_clear.clicked.connect(self._clear)
        opts.add_layout(row(btn_clear, QLabel(""), stretch_last=True))
        self.body.addWidget(opts)
        self.body.addStretch(1)

        self.refresh_count()

    def _on_toggled(self, on: bool) -> None:
        self.hist_max.setEnabled(on)
        self.emit_changed()

    # ---- 数据 ----

    def set_history(self, history) -> None:
        """历史开关切换后,App 会换掉 History 对象(或置空)。"""
        self._history = history
        self.refresh_count()

    def refresh_count(self) -> None:
        if self._history is None:
            self.count_label.setText("历史记录已关闭")
            return
        self.count_label.setText(f"当前共 {self._history.count()} 条")

    def _clear(self) -> None:
        if self._history is None:
            return
        ok = QMessageBox.question(
            self, "清空历史", "确定要删除全部识别历史吗?此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok == QMessageBox.StandardButton.Yes:
            self._history.clear()
            self.refresh_count()

    # ---- 写回 ----

    def collect(self, cfg: Config) -> None:
        cfg.history.enabled = self.hist_enabled.isChecked()
        cfg.history.max_entries = self.hist_max.value()
