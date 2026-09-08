"""「词典」页:术语替换表。

模型解决不了的专有名词靠这里兜 —— 实测 SenseVoice 会把 keytyper 听成
keyper、pytest 听成 P test。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from ...config import Config
from ..widgets import Card, hint
from .base import Page


class DictionaryPage(Page):
    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(scroll=False, parent=parent)   # 表格自己会滚

        card = Card("术语替换")
        card.add(hint(
            "识别结果里左边的词会被整体换成右边的,不区分大小写。"
            "实测 SenseVoice 会把 keytyper 听成 keyper、pytest 听成 P test,"
            "这类专有名词模型解决不了,靠这里兜。"
        ))

        self.dict_table = QTableWidget(0, 2)
        self.dict_table.setHorizontalHeaderLabels(["识别成(错的)", "替换为(对的)"])
        self.dict_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.dict_table.verticalHeader().setVisible(False)
        self.dict_table.itemChanged.connect(self.emit_changed)
        self._fill(cfg.replacements)
        card.add(self.dict_table)

        btns = QHBoxLayout()
        add = QPushButton("添加一行")
        add.clicked.connect(self._add_row)
        remove = QPushButton("删除选中")
        remove.setProperty("role", "danger")
        remove.clicked.connect(self._remove_rows)
        btns.addWidget(add)
        btns.addWidget(remove)
        btns.addStretch(1)
        card.add_layout(btns)

        self.body.addWidget(card, 1)

    def prefill(self, text: str) -> None:
        """从「历史」页带一句话过来,新建一行 —— 省得再凭记忆手打一遍。

        **左边默认整句填进去,不是拆出单个词。** 词典存的是词级替换,
        但这里不知道这句话里到底是哪个词被听错了;删掉多余的部分
        比凭记忆重打一遍轻松。焦点直接停在左边格子上,方便当场删改,
        改完按 Tab 就能接着填右边那格。
        """
        item = self._insert_row(text, "")
        self.dict_table.scrollToItem(item)
        self.dict_table.editItem(item)

    def _fill(self, replacements: dict[str, str]) -> None:
        was, self._loading = self._loading, True
        self.dict_table.setRowCount(0)
        for src, dst in sorted(replacements.items()):
            self._insert_row(src, dst)
        self._loading = was

    def _add_row(self) -> None:
        self.dict_table.editItem(self._insert_row("", ""))

    def _insert_row(self, src: str, dst: str) -> QTableWidgetItem:
        """插一行,返回左边那格 —— 三个调用方都要拿它去做点别的事
        (定位光标、继续插下一行、或者什么都不做)。

        **必须挡住 `_loading`。** 两个 `setItem` 各触发一次 `itemChanged`,
        不挡的话,新建一行(不管是空的还是从历史带过来的)会在用户
        还没打一个字之前就把"配置变了"的防抖计时器敲响 —— 这条是写
        `prefill()` 的测试时顺带在旁边的 `_add_row()` 里也发现的。
        """
        was, self._loading = self._loading, True
        r = self.dict_table.rowCount()
        self.dict_table.insertRow(r)
        self.dict_table.setItem(r, 0, QTableWidgetItem(src))
        self.dict_table.setItem(r, 1, QTableWidgetItem(dst))
        self._loading = was
        return self.dict_table.item(r, 0)

    def _remove_rows(self) -> None:
        rows = sorted({i.row() for i in self.dict_table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        was, self._loading = self._loading, True
        for r in rows:
            self.dict_table.removeRow(r)
        self._loading = was
        self.emit_changed()

    # ---- 写回 ----

    def collect(self, cfg: Config) -> None:
        out: dict[str, str] = {}
        for r in range(self.dict_table.rowCount()):
            src_item = self.dict_table.item(r, 0)
            dst_item = self.dict_table.item(r, 1)
            src = (src_item.text() if src_item else "").strip()
            dst = (dst_item.text() if dst_item else "").strip()
            if src:          # 空的目标是合法的:表示"删掉这个词"
                out[src] = dst
        cfg.replacements = out
