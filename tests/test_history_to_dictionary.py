"""历史页「加入词典」:把选中的原句带到词典页,省得凭记忆重打一遍。

以前发现识别老听错同一个词,得先记住这句话说的是什么、手动切到词典页、
再把那个词重打一遍。这条链路直接把原句带过去。
"""

from __future__ import annotations

import pytest

from voiceinput.config import Config
from voiceinput.history import History
from voiceinput.ui import theme
from voiceinput.ui.main_window import MainWindow


@pytest.fixture
def window(qapp, tmp_path):
    h = History(path=tmp_path / "h.db")
    h.add("把这个 function 改成 async", "把这个 function 改成 async", 1.0, 0.2, "sensevoice")
    w = MainWindow(Config(), theme.DARK, h)
    w.history.reload()
    yield w
    h.close()


class TestHistoryButton:
    def test_没选中行时不发信号(self, window):
        seen = []
        window.history.addToDictionaryRequested.connect(seen.append)
        window.history._add_to_dictionary()
        assert seen == []

    def test_选中行之后带着原句发信号(self, window):
        window.history.hist_table.selectRow(0)
        seen = []
        window.history.addToDictionaryRequested.connect(seen.append)
        window.history._add_to_dictionary()
        assert seen == ["把这个 function 改成 async"]


class TestDictionaryPrefill:
    def test_新建一行左边填整句(self, window):
        before = window.dictionary.dict_table.rowCount()
        window.dictionary.prefill("把这个 function 改成 async")
        assert window.dictionary.dict_table.rowCount() == before + 1
        r = window.dictionary.dict_table.rowCount() - 1
        assert window.dictionary.dict_table.item(r, 0).text() == \
            "把这个 function 改成 async"
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
    def test_点了加入词典之后自动切到词典页(self, window):
        window.tabs.setCurrentWidget(window.history)
        window.history.hist_table.selectRow(0)
        window.history._add_to_dictionary()
        assert window.tabs.currentWidget() is window.dictionary

    def test_词典页真的多了一行带着原句的(self, window):
        window.history.hist_table.selectRow(0)
        before = window.dictionary.dict_table.rowCount()
        window.history._add_to_dictionary()
        assert window.dictionary.dict_table.rowCount() == before + 1
        r = window.dictionary.dict_table.rowCount() - 1
        assert window.dictionary.dict_table.item(r, 0).text() == \
            "把这个 function 改成 async"
