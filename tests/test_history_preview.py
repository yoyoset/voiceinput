"""历史页表格那一列太窄,长句子会被截断,用户点开找不到看全文的地方。

修法是选中一行时在表格上方显示完整文本 —— 不用双击(那个是重新粘贴,
会真的把文字发到别的窗口去),单击就能看,没有副作用。
"""

from __future__ import annotations

import pytest

from voiceinput.config import Config
from voiceinput.history import History
from voiceinput.ui import theme
from voiceinput.ui.main_window import MainWindow

_LONG_TEXT = "这是一句很长很长很长很长很长很长很长很长很长很长很长很长很长很长的话,用来测试表格列宽是不是真的截断了它"


@pytest.fixture
def window(qapp, tmp_path):
    h = History(path=tmp_path / "h.db")
    h.add(_LONG_TEXT, _LONG_TEXT, 1.0, 0.2, "sensevoice")
    w = MainWindow(Config(), theme.DARK, h)
    w.history.reload()
    yield w
    h.close()


class TestPreview:
    def test_没选中行时是占位文案(self, window):
        assert window.history.hist_preview.text() == "点一行,这里显示完整内容"

    def test_选中一行就显示完整文本(self, window):
        window.history.hist_table.selectRow(0)
        assert window.history.hist_preview.text() == _LONG_TEXT

    def test_长句子完整出现在预览里_不是表格里被截断的那份(self, window):
        """**这是这个功能存在的意义。** 表格列窄会截断,预览不能也截断。"""
        window.history.hist_table.selectRow(0)
        assert window.history.hist_preview.text() == _LONG_TEXT
        assert len(window.history.hist_preview.text()) == len(_LONG_TEXT)

    def test_重新加载会清空预览(self, window):
        """`reload()` 会清空表格重建,选中状态跟着没了 ——
        预览要是还停在上一次选的内容,就是在说谎。"""
        window.history.hist_table.selectRow(0)
        window.history.reload()
        assert window.history.hist_preview.text() == "点一行,这里显示完整内容"

    def test_每个单元格都带完整文本的_tooltip(self, window):
        """双击是"重新粘贴"这个有副作用的动作,不适合拿来"就想看看"。
        鼠标停留能看一眼是更轻的路径,兜个底。"""
        item = window.history.hist_table.item(0, 1)
        assert item.toolTip() == _LONG_TEXT
