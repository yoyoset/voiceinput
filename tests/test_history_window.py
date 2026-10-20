"""独立历史窗口。

起因:「历史」分页挤在设置窗口里,表格只露出一行半,用户说"根本看不见,
没办法去选"。偏偏找历史是最急的时候 —— 刚说完一大段没粘进去
(2026-09-15 18:21 连丢两句,识别都成功了,文字只在历史里)。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication

from voiceinput.history import History
from voiceinput.ui import theme
from voiceinput.ui.history_window import (
    _META_ROLE,
    _TEXT_ROLE,
    HistoryWindow,
    describe_time,
)
from voiceinput.ui.tray import Tray

_LONG = ("是这样，你这个模型只能测到填充的问题啊，你没有办法测到内切线的圆走直线的问题啊。"
         "因为你这都是圆啊，不是圆环啊，这些这些圆都没有内切线啊，而且即便是它切了，你在外面也看不出来啊。")


@pytest.fixture
def db(tmp_path):
    h = History(path=tmp_path / "h.db")
    h.add("第一条", "第一条", 2.0, 0.1)
    h.add(_LONG, _LONG, 20.0, 1.5)
    yield h
    h.close()


@pytest.fixture
def win(qapp, db):
    w = HistoryWindow(theme.DARK, db)
    yield w
    w.hide()
    w.deleteLater()


# ---- 时间怎么说 ----


def _ts(*args) -> float:
    return datetime(*args).timestamp()


class TestDescribeTime:
    NOW = _ts(2026, 9, 15, 18, 30, 0)

    def test_今天(self):
        assert describe_time(_ts(2026, 9, 15, 18, 21, 30), self.NOW) == "今天 18:21:30"

    def test_昨天(self):
        assert describe_time(_ts(2026, 9, 14, 23, 0, 5), self.NOW) == "昨天 23:00:05"

    def test_今年更早(self):
        assert describe_time(_ts(2026, 9, 10, 8, 0, 0), self.NOW) == "09-10 08:00:00"

    def test_跨年带年份(self):
        assert describe_time(_ts(2025, 12, 31, 8, 0, 0), self.NOW) == "2025-12-31 08:00:00"


# ---- 列表 ----


def test_最新的在最上面_正文完整不截断(win):
    assert win.list.count() == 2
    assert win.list.item(0).data(_TEXT_ROLE) == _LONG
    assert win.list.item(1).data(_TEXT_ROLE) == "第一条"


def test_每条带时间和语音时长(win):
    meta = win.list.item(0).data(_META_ROLE)
    assert meta.startswith("今天 ")
    assert "20 秒语音" in meta


def test_长句子的卡片比短句子高(win):
    """**这是整个窗口存在的意义**:高度跟着换行数走,不是表格那种固定行高截断。"""
    win.resize(500, 600)
    win.show()
    QApplication.processEvents()
    long_h = win.list.visualItemRect(win.list.item(0)).height()
    short_h = win.list.visualItemRect(win.list.item(1)).height()
    assert long_h > short_h


@pytest.mark.parametrize("width", [760, 460])
def test_卡片高度按当前宽度算_不互相盖住(win, db, width):
    """实测踩过:第一次打开时滚动条刚出现、视口变窄,高度还是按旧宽度算的,
    长句子那张卡片少了一行高,盖住了下面那张。**不等延迟重排定时器**,
    只 processEvents 一次就查。"""
    for i in range(12):
        db.add(_LONG * (i % 3 + 1), "", 1.0, 0.1)
    win.resize(width, 500)
    win.open()
    QApplication.processEvents()
    lst = win.list
    for i in range(lst.count()):
        idx = lst.indexFromItem(lst.item(i))
        want = win._delegate.sizeHint(lst.viewOptions() if hasattr(lst, "viewOptions")
                                      else _option(lst), idx).height()
        assert lst.visualItemRect(lst.item(i)).height() == want, f"第 {i} 条"


def _option(view):
    from PySide6.QtWidgets import QStyleOptionViewItem

    opt = QStyleOptionViewItem()
    opt.initFrom(view)
    opt.font = view.font()
    return opt


def test_打开时默认选中最新一条(win):
    """来找的多半就是刚才没粘进去的那句,打开直接回车就能粘。"""
    win.list.clearSelection()
    win.open()
    assert win.selected_text() == _LONG


def test_打开时清掉上次的搜索词(win):
    win.search.setText("第一")
    win.open()
    assert win.search.text() == ""
    assert win.list.count() == 2


def test_搜索(win):
    win.search.setText("内切线")
    assert win.list.count() == 1
    assert win.count_label.text() == "找到 1 条"


def test_搜不到时说清楚(win):
    win.search.setText("不存在的词")
    assert win.list.count() == 0
    assert not win.btn_paste.isEnabled()
    assert "不存在的词" in win.empty.text()


def test_历史关着不炸_并告诉怎么打开(qapp):
    w = HistoryWindow(theme.DARK, None)
    assert w.list.count() == 0
    assert "记录识别历史" in w.empty.text()
    assert not w.btn_copy.isEnabled()
    w.deleteLater()


def test_有新记录时开着才刷新(win, db):
    db.add("新的一句", "新的一句", 1.0, 0.1)
    win.refresh()                       # 没开着:不刷
    assert win.list.count() == 2
    win.open()
    db.add("又一句", "又一句", 1.0, 0.1)
    win.refresh()
    assert win.list.count() == 4


def test_刷新保持选中的那条(win, db):
    """正在选着某条时来了一句新的,选中不能被顶到别的条上 ——
    不然按回车粘出去的不是自己选的那句。"""
    win.list.setCurrentRow(1)
    db.add("新来的", "新来的", 1.0, 0.1)
    win.reload()
    assert win.selected_text() == "第一条"


# ---- 动作 ----


def test_复制是完整原文(win):
    win.list.setCurrentRow(0)
    win.copy_selected()
    assert QApplication.clipboard().text() == _LONG
    assert "已复制" in win.note.text()


def test_粘贴发出完整原文(win):
    seen = []
    win.repasteRequested.connect(seen.append)
    win.list.setCurrentRow(0)
    win.repaste_selected()
    assert seen == [_LONG]


def test_删除后停在原位置(win, db):
    db.add("第三条", "第三条", 1.0, 0.1)
    win.reload()
    win.list.setCurrentRow(1)            # 中间那条 = _LONG
    win.delete_selected()
    assert db.count() == 2
    assert win.list.currentRow() == 1
    assert _LONG not in [win.list.item(i).data(_TEXT_ROLE) for i in range(win.list.count())]


def test_关窗口只是隐藏(win):
    win.open()
    win.close()
    assert not win.isVisible()


# ---- 入口 ----


def test_托盘菜单里能直接打开历史(qapp):
    """悬浮麦克风的右键菜单就是这一份,所以右键麦克风也能打开。"""
    t = Tray(theme.DARK)
    act = next(a for a in t.contextMenu().actions() if a.text() == "历史记录")
    seen = []
    t.historyRequested.connect(lambda: seen.append(True))
    act.trigger()
    assert seen == [True]


def test_历史分页有按钮打开大窗口(qapp, db):
    from voiceinput.config import Config
    from voiceinput.ui.main_window import MainWindow

    w = MainWindow(Config(), theme.DARK, db)
    seen = []
    w.historyWindowRequested.connect(lambda: seen.append(True))
    w.history.btn_window.click()
    assert seen == [True]
    w.deleteLater()


def test_重新粘贴前历史窗口也要让出焦点(qapp):
    """从历史窗口点粘贴,前台是历史窗口自己 —— 不藏起来就粘进自己的搜索框。"""
    from voiceinput.app import App

    class FakeWin:
        def __init__(self, visible):
            self.visible = visible

        def isVisible(self):  # noqa: N802
            return self.visible

        def hide(self):
            self.visible = False

    class FakeApp:
        _yield_focus = App._yield_focus

    app = FakeApp()
    app.window, app.history_window = FakeWin(False), FakeWin(True)
    assert app._yield_focus() is True
    assert not app.history_window.visible

    app.history_window.visible = False
    assert app._yield_focus() is False
