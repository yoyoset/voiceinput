"""独立的历史窗口:把没粘进去的那句话找回来。

**为什么不是只修「历史」分页**:分页挤在设置窗口里,上面是状态条和选项卡,
下面是预览卡片、四个按钮、说明文字、记录设置 —— 留给表格的只剩一行半,
用户的原话是"根本看不见,没办法去选"。而找历史的时刻恰恰是最急的时候
(刚说完一大段,没粘进去),不该先去翻设置。

所以做成托盘/悬浮麦克风右键就能直接打开的独立窗口,只干一件事:
每条**完整换行显示**(不截断、不用再点一下看预览),选中 → 粘贴或复制。

列表用自绘委托而不是 QTableWidget:表格的行高是固定的,长句子只能截断;
委托按可用宽度算每条的高度,多长都能完整显示。
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .theme import Palette

_TEXT_ROLE = Qt.ItemDataRole.UserRole
_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_META_ROLE = Qt.ItemDataRole.UserRole + 2

# 一次最多列多少条。再往前的靠搜索找 —— 往下翻几百条找一句话没人会做。
LIMIT = 500

MARGIN, PAD_X, PAD_Y, GAP = 4, 14, 10, 5
BODY_PX, META_PX = 14, 12

_WRAP = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap


def describe_time(ts: float, now: float | None = None) -> str:
    """"今天 18:21:30" / "昨天 …" / "09-13 …" / "2025-09-13 …"。

    找丢了的那句话时,人记得的是"刚才""昨天晚上",不是日期。
    """
    t = datetime.fromtimestamp(ts)
    n = datetime.fromtimestamp(now) if now is not None else datetime.now()
    clock = t.strftime("%H:%M:%S")
    days = (n.date() - t.date()).days
    if days == 0:
        return f"今天 {clock}"
    if days == 1:
        return f"昨天 {clock}"
    if t.year == n.year:
        return f"{t:%m-%d} {clock}"
    return f"{t:%Y-%m-%d} {clock}"


class _EntryDelegate(QStyledItemDelegate):
    """一条历史画成一张卡片:上面一行小字时间,下面完整换行的正文。

    **sizeHint 和 paint 必须用同一个文字宽度算**,否则算出来的高度装不下
    画出来的行数,最后一行被裁掉 —— 那正好又是"看不全"。
    """

    def __init__(self, view: QListWidget, palette: Palette) -> None:
        super().__init__(view)
        self._view = view
        self._palette = palette

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette

    @staticmethod
    def _fonts(base: QFont) -> tuple[QFont, QFont]:
        body, meta = QFont(base), QFont(base)
        body.setPixelSize(BODY_PX)
        meta.setPixelSize(META_PX)
        return body, meta

    @staticmethod
    def _text_width(item_width: int) -> int:
        return max(80, item_width - 2 * MARGIN - 2 * PAD_X)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        # 用视口宽度而不是 option.rect:列表模式下 sizeHint 拿到的 rect 常常是空的
        width = self._view.viewport().width()
        body, meta = self._fonts(option.font)
        text = index.data(_TEXT_ROLE) or ""
        body_h = QFontMetrics(body).boundingRect(
            QRect(0, 0, self._text_width(width), 1_000_000), _WRAP, text).height()
        meta_h = QFontMetrics(meta).height()
        return QSize(width, 2 * MARGIN + 2 * PAD_Y + meta_h + GAP + body_h)

    def paint(self, painter: QPainter, option, index) -> None:
        p = self._palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        body, meta = self._fonts(option.font)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = option.rect.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        painter.setPen(QPen(QColor(p.accent if selected else p.border),
                            1.6 if selected else 1.0))
        painter.setBrush(QColor(p.surface_alt if (selected or hovered) else p.surface))
        painter.drawRoundedRect(QRectF(card).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        inner = card.adjusted(PAD_X, PAD_Y, -PAD_X, -PAD_Y)
        meta_h = QFontMetrics(meta).height()
        painter.setFont(meta)
        painter.setPen(QColor(p.accent if selected else p.text_dim))
        painter.drawText(QRect(inner.left(), inner.top(), inner.width(), meta_h),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         index.data(_META_ROLE) or "")

        painter.setFont(body)
        painter.setPen(QColor(p.text))
        top = inner.top() + meta_h + GAP
        painter.drawText(QRect(inner.left(), top, inner.width(), inner.bottom() - top + 1),
                         _WRAP, index.data(_TEXT_ROLE) or "")
        painter.restore()


class HistoryWindow(QWidget):
    """历史记录窗口。关掉只是隐藏,下次打开不用重建。"""

    repasteRequested = Signal(str)
    addToDictionaryRequested = Signal(str)
    """"这句里有个词老被听错" —— 带着原句去词典页新建一行,省得凭记忆重打。"""

    def __init__(self, palette: Palette, history, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._history = history
        self.setWindowTitle("历史记录 — VoiceInput")
        self.resize(760, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("历史记录")
        title.setProperty("role", "title")
        self.count_label = QLabel("")
        self.count_label.setProperty("role", "subtitle")
        head.addWidget(title)
        head.addSpacing(8)
        head.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        layout.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索说过的话…(↓ 键跳到列表)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setProperty("role", "entries")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.verticalScrollBar().setSingleStep(24)
        # 卡片宽度 = 视口宽度,横向滚动条永远用不上;留着它会在
        # "竖滚动条出现 → 视口变窄"那一瞬间闪出来
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 窗口一变宽窄就重新排版,每条的高度跟着换行数重新算
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setUniformItemSizes(False)
        self.list.setMouseTracking(True)
        # Adjust 模式的重排是延迟定时器触发的。实测:第一次打开时竖滚动条
        # 刚冒出来、视口变窄了 11px,高度却还是按没滚动条时算的 —— 四行的
        # 那条只留了三行的高,盖住了下面一张卡片。宽度一变就立刻重排。
        self._layout_width = -1
        self.list.viewport().installEventFilter(self)
        self._delegate = _EntryDelegate(self.list, palette)
        self.list.setItemDelegate(self._delegate)
        self.list.itemSelectionChanged.connect(self._on_selection)
        # 双击 / 回车 = 粘贴回去,和「历史」分页的双击一致
        self.list.itemActivated.connect(lambda _item: self.repaste_selected())
        layout.addWidget(self.list, 1)

        self.empty = QLabel("")
        self.empty.setProperty("role", "hint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty, 1)

        acts = QHBoxLayout()
        self.btn_paste = QPushButton("粘贴到上一个窗口")
        self.btn_paste.setProperty("role", "primary")
        self.btn_paste.clicked.connect(self.repaste_selected)
        self.btn_copy = QPushButton("复制")
        self.btn_copy.clicked.connect(self.copy_selected)
        self.btn_dict = QPushButton("加入词典")
        self.btn_dict.clicked.connect(self.add_selected_to_dictionary)
        self.note = QLabel("")
        self.note.setProperty("role", "hint")
        self.btn_delete = QPushButton("删除")
        self.btn_delete.setProperty("role", "danger")
        self.btn_delete.clicked.connect(self.delete_selected)
        acts.addWidget(self.btn_paste)
        acts.addWidget(self.btn_copy)
        acts.addWidget(self.btn_dict)
        acts.addSpacing(8)
        acts.addWidget(self.note, 1)
        acts.addWidget(self.btn_delete)
        layout.addLayout(acts)

        tips = QLabel("双击或回车:粘贴到你上一个使用的窗口(本窗口会先自动隐藏)"
                      " · Ctrl+C 复制 · Del 删除 · Esc 关闭")
        tips.setProperty("role", "hint")
        tips.setWordWrap(True)
        layout.addWidget(tips)

        for keys, slot, target in (
            (QKeySequence(QKeySequence.StandardKey.Copy), self.copy_selected, self.list),
            (QKeySequence(Qt.Key.Key_Delete), self.delete_selected, self.list),
            (QKeySequence(Qt.Key.Key_Escape), self.hide, self),
            (QKeySequence(QKeySequence.StandardKey.Find), self.search.setFocus, self),
        ):
            sc = QShortcut(keys, target)
            if target is self.list:
                # 只在列表上生效:搜索框里 Ctrl+C / Del 是改搜索词的
                sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            else:
                sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

        self.reload()

    # ---- 打开 / 外部通知 ----

    def open(self) -> None:
        """刷新并拉到最前。默认选中最新一条 —— 来找的多半就是刚才那句。"""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.reload()
        if self.list.count():
            self.list.setCurrentRow(0)
        self.show()
        self.raise_()
        self.activateWindow()
        self.list.setFocus()

    def refresh(self) -> None:
        """有新记录了。开着就刷新,没开着什么都不做(打开时本来就会刷)。"""
        if self.isVisible():
            self.reload()

    def set_history(self, history) -> None:
        """历史开关切换后 History 对象会换掉(或者变成 None)。"""
        self._history = history
        self.reload()

    def set_palette(self, palette: Palette) -> None:
        self._delegate.set_palette(palette)
        self.list.viewport().update()

    # ---- 数据 ----

    def reload(self) -> None:
        keep = self._selected_id()
        self.list.clear()
        self.note.setText("")

        if self._history is None:
            self._show_empty("历史记录已关闭。\n在「设置 → 历史」里勾上「记录识别历史」。")
            self.count_label.setText("")
            return

        query = self.search.text().strip()
        entries = self._history.recent(limit=LIMIT, search=query)
        for e in entries:
            item = QListWidgetItem()
            item.setData(_TEXT_ROLE, e.text)
            item.setData(_ID_ROLE, e.id)
            item.setData(_META_ROLE, f"{describe_time(e.created_at)}    ·    {e.audio_s:.0f} 秒语音")
            self.list.addItem(item)

        if not entries:
            self._show_empty(f"没有包含「{query}」的记录" if query else "还没有记录")
        else:
            self.empty.hide()
            self.list.show()
            row = next((i for i in range(self.list.count())
                        if self.list.item(i).data(_ID_ROLE) == keep), 0)
            self.list.setCurrentRow(row)

        if query:
            self.count_label.setText(f"找到 {len(entries)} 条")
        elif len(entries) >= LIMIT:
            self.count_label.setText(f"最近 {LIMIT} 条,更早的请搜索")
        else:
            self.count_label.setText(f"共 {len(entries)} 条")
        self._update_buttons()

    def _show_empty(self, text: str) -> None:
        self.empty.setText(text)
        self.list.hide()
        self.empty.show()
        self._update_buttons()

    def _selected_item(self) -> QListWidgetItem | None:
        items = self.list.selectedItems()
        return items[0] if items else None

    def _selected_id(self) -> int | None:
        item = self._selected_item()
        return item.data(_ID_ROLE) if item else None

    def selected_text(self) -> str:
        item = self._selected_item()
        return (item.data(_TEXT_ROLE) or "") if item else ""

    def _on_selection(self) -> None:
        self.note.setText("")
        self._update_buttons()

    def _update_buttons(self) -> None:
        has = self._selected_item() is not None
        for b in (self.btn_paste, self.btn_copy, self.btn_dict, self.btn_delete):
            b.setEnabled(has)

    # ---- 动作 ----

    def repaste_selected(self) -> None:
        text = self.selected_text()
        if text:
            self.repasteRequested.emit(text)

    def copy_selected(self) -> None:
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)
            # 复制没有任何可见的变化,不说一声用户会怀疑到底复制上没有
            self.note.setText("已复制,去目标窗口 Ctrl+V 即可")

    def add_selected_to_dictionary(self) -> None:
        text = self.selected_text()
        if text:
            self.addToDictionaryRequested.emit(text)

    def delete_selected(self) -> None:
        entry_id = self._selected_id()
        if self._history is None or entry_id is None:
            return
        row = self.list.currentRow()
        self._history.delete(entry_id)
        self.reload()
        # 删完停在原来的位置,不跳回第一条 —— 连删几条时不用每次重新找
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))

    # ---- 事件 ----

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # 搜索框在列表之前就装了过滤器,构造过程中事件已经会进来
        if not hasattr(self, "_delegate"):
            return False
        if obj is self.list.viewport() and event.type() == QEvent.Type.Resize:
            width = self.list.viewport().width()
            if width != self._layout_width:
                self._layout_width = width
                self.list.doItemsLayout()
            return False
        if (obj is self.search and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and self.list.count()):
            # 回车在搜索框里**不**直接粘贴:还在打搜索词时手一滑就发出去了
            self.list.setFocus()
            if self._selected_item() is None:
                self.list.setCurrentRow(0)
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:  # noqa: N802
        """关掉只是隐藏。程序靠托盘常驻,不能因为关了一个窗口就退出。"""
        event.ignore()
        self.hide()
