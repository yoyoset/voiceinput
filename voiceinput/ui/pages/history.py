"""「历史」页:说过的每一句话,能搜、能重新粘贴、能删。"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from ...config import Config
from ..widgets import Card, hint, labeled, spin
from .base import Page

_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class HistoryPage(Page):
    repasteRequested = Signal(str)
    addToDictionaryRequested = Signal(str)
    """"这句里有个词被听错了" —— 带着选中的文本去词典页新建一行。"""

    def __init__(self, cfg: Config, history, parent=None) -> None:
        super().__init__(scroll=False, parent=parent)   # 表格自己会滚
        self._history = history

        bar = QHBoxLayout()
        self.hist_search = QLineEdit()
        self.hist_search.setPlaceholderText("搜索历史…")
        self.hist_search.textChanged.connect(self.reload)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.reload)
        btn_clear = QPushButton("清空")
        btn_clear.setProperty("role", "danger")
        btn_clear.clicked.connect(self._clear)
        bar.addWidget(self.hist_search, 1)
        bar.addWidget(btn_refresh)
        bar.addWidget(btn_clear)
        self.body.addLayout(bar)

        self.hist_table = QTableWidget(0, 3)
        self.hist_table.setHorizontalHeaderLabels(["时间", "文本", "耗时"])
        self._size_columns()
        self.hist_table.verticalHeader().setVisible(False)
        self.hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hist_table.doubleClicked.connect(self.repaste_selected)
        self.hist_table.itemSelectionChanged.connect(self._update_preview)
        self.body.addWidget(self.hist_table, 1)

        # 表格那一列太窄,长一点的句子直接被截断,连自己说了什么都看不清 ——
        # 双击又是直接触发粘贴,不适合拿来"就想看看内容"。选中一行,
        # 这里原样显示完整文本,不用猜、也不会顺手把东西粘到别的窗口去。
        preview = Card("选中内容")
        self.hist_preview = QLabel("点一行,这里显示完整内容")
        self.hist_preview.setWordWrap(True)
        self.hist_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview.add(self.hist_preview)
        self.body.addWidget(preview)

        acts = QHBoxLayout()
        btn_paste = QPushButton("重新粘贴选中")
        btn_paste.setProperty("role", "primary")
        btn_paste.clicked.connect(self.repaste_selected)
        btn_copy = QPushButton("复制到剪贴板")
        btn_copy.clicked.connect(self._copy_selected)
        # 识别老听错同一个词,以前得先记住这句话说的是什么、切到词典页、
        # 再凭记忆重打一遍。这里直接把选中的原句带过去,省一遍手打。
        btn_dict = QPushButton("加入词典")
        btn_dict.clicked.connect(self._add_to_dictionary)
        # 之前只能「清空」全部。说错一句、或者说了不想留的内容,
        # 唯一的办法是把整个历史都删掉 —— 太粗暴了。
        btn_del = QPushButton("删除选中")
        btn_del.setProperty("role", "danger")
        btn_del.clicked.connect(self._delete_selected)
        for b in (btn_paste, btn_copy, btn_dict, btn_del):
            acts.addWidget(b)
        acts.addStretch(1)
        self.body.addLayout(acts)
        self.body.addWidget(hint(
            "单击一行,上面「选中内容」里会显示完整文本 —— 表格那一列太窄,"
            "长句子会被截断。\n"
            "双击一行即可重新粘贴。点击后本窗口会自动隐藏,"
            "文字粘贴到你上一个使用的窗口 —— 不用先切过去。\n"
            "「加入词典」把选中的原句整句带到词典页新建一行,"
            "删掉多余部分、留下听错的那个词,再填对的写法即可。"
        ))

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
        opts.add(hint("超出后自动删最旧的。关掉记录不会删已有的,想清空请点上面的「清空」。"))
        self.body.addWidget(opts)

    def _size_columns(self) -> None:
        header = self.hist_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        # 表头默认居中,内容是左对齐的,不改的话"文本"这一列头尾对不上
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _on_toggled(self, on: bool) -> None:
        self.hist_max.setEnabled(on)
        self.emit_changed()

    # ---- 数据 ----

    def set_history(self, history) -> None:
        """历史开关切换后,App 会换掉 History 对象(或置空)。"""
        self._history = history
        self.hist_table.setRowCount(0)
        self.reload()

    def reload(self) -> None:
        if self._history is None:
            return
        entries = self._history.recent(limit=300, search=self.hist_search.text().strip())
        self.hist_table.setRowCount(0)
        for e in entries:
            r = self.hist_table.rowCount()
            self.hist_table.insertRow(r)
            when = time.strftime("%m-%d %H:%M:%S", time.localtime(e.created_at))
            item_text = QTableWidgetItem(e.text)
            item_text.setData(Qt.ItemDataRole.UserRole, e.text)
            item_text.setData(_ID_ROLE, e.id)          # 删除时用
            item_text.setToolTip(e.text)   # 列太窄截断时,鼠标停留至少能看一眼
            item_cost = QTableWidgetItem(f"{e.infer_s:.2f}s")
            item_cost.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.hist_table.setItem(r, 0, QTableWidgetItem(when))
            self.hist_table.setItem(r, 1, item_text)
            self.hist_table.setItem(r, 2, item_cost)
        self._update_preview()   # 重新加载会清掉选中状态,预览也要跟着清空

    def _update_preview(self) -> None:
        text = self._selected_text()
        self.hist_preview.setText(text or "点一行,这里显示完整内容")

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.hist_table.selectedIndexes()})

    def _selected_text(self) -> str:
        rows = self._selected_rows()
        if not rows:
            return ""
        item = self.hist_table.item(rows[0], 1)
        return item.text() if item else ""

    # ---- 动作 ----

    def repaste_selected(self) -> None:
        text = self._selected_text()
        if text:
            self.repasteRequested.emit(text)

    def _copy_selected(self) -> None:
        text = self._selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def _add_to_dictionary(self) -> None:
        text = self._selected_text()
        if text:
            self.addToDictionaryRequested.emit(text)

    def _delete_selected(self) -> None:
        if self._history is None:
            return
        ids = []
        for r in self._selected_rows():
            item = self.hist_table.item(r, 1)
            if item is not None and item.data(_ID_ROLE) is not None:
                ids.append(item.data(_ID_ROLE))
        if not ids:
            return
        for entry_id in ids:
            self._history.delete(entry_id)
        self.reload()

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
            self.reload()

    # ---- 写回 ----

    def collect(self, cfg: Config) -> None:
        cfg.history.enabled = self.hist_enabled.isChecked()
        cfg.history.max_entries = self.hist_max.value()
