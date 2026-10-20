"""「加入词典」:把选中的原句带到词典页,省得凭记忆重打一遍。

以前发现识别老听错同一个词,得先记住这句话说的是什么、手动切到词典页、
再把那个词重打一遍。这条链路直接把原句带过去。

按钮原来在设置里的「历史」页,那一页的列表去掉之后挪到了独立的历史窗口。
"""

from __future__ import annotations

import pytest

from voiceinput.config import Config
from voiceinput.history import History
from voiceinput.ui import theme
from voiceinput.ui.history_window import HistoryWindow
from voiceinput.ui.main_window import MainWindow

_TEXT = "把这个 function 改成 async"


@pytest.fixture
def db(tmp_path):
    h = History(path=tmp_path / "h.db")
    h.add(_TEXT, _TEXT, 1.0, 0.2, "sensevoice")
    yield h
    h.close()


@pytest.fixture
def window(qapp, db):
    return MainWindow(Config(), theme.DARK, db)


class TestHistoryButton:
    def test_没选中时不发信号(self, qapp, db):
        w = HistoryWindow(theme.DARK, db)
        w.list.clearSelection()
        seen = []
        w.addToDictionaryRequested.connect(seen.append)
        w.add_selected_to_dictionary()
        assert seen == []
        assert not w.btn_dict.isEnabled()

    def test_选中之后带着原句发信号(self, qapp, db):
        w = HistoryWindow(theme.DARK, db)
        w.list.setCurrentRow(0)
        seen = []
        w.addToDictionaryRequested.connect(seen.append)
        w.btn_dict.click()
        assert seen == [_TEXT]


class TestDictionaryPrefill:
    def test_新建一行左边填整句(self, window):
        before = window.dictionary.dict_table.rowCount()
        window.dictionary.prefill(_TEXT)
        assert window.dictionary.dict_table.rowCount() == before + 1
        r = window.dictionary.dict_table.rowCount() - 1
        assert window.dictionary.dict_table.item(r, 0).text() == _TEXT
        assert window.dictionary.dict_table.item(r, 1).text() == ""

    def test_不会当成配置变了而触发防抖落盘(self, window):
        """**这是从别处带数据过来,不是用户在编辑。**
        新建一行本身不该被误当成"用户改完了、该存盘了"。
        """
        seen = []
        window.dictionary.changed.connect(lambda: seen.append(1))
        window.dictionary.prefill("测试文本")
        assert seen == []


class TestEndToEnd:
    def test_加入词典之后自动切到词典页(self, window):
        window.tabs.setCurrentWidget(window.general)
        window.add_to_dictionary(_TEXT)
        assert window.tabs.currentWidget() is window.dictionary

    def test_词典页真的多了一行带着原句的(self, window):
        before = window.dictionary.dict_table.rowCount()
        window.add_to_dictionary(_TEXT)
        assert window.dictionary.dict_table.rowCount() == before + 1
        r = window.dictionary.dict_table.rowCount() - 1
        assert window.dictionary.dict_table.item(r, 0).text() == _TEXT
