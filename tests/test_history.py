
from voiceinput.history import History


def make(tmp_path, **kw) -> History:
    return History(path=tmp_path / "h.db", **kw)


class TestHistory:
    def test_add_and_read(self, tmp_path):
        h = make(tmp_path)
        h.add("你好世界", "<|zh|>你好世界", 2.0, 0.11, "sensevoice")
        entries = h.recent()
        assert len(entries) == 1
        assert entries[0].text == "你好世界"
        assert entries[0].raw_text == "<|zh|>你好世界"
        assert entries[0].rtf == 0.055
        h.close()

    def test_newest_first(self, tmp_path):
        h = make(tmp_path)
        for i in range(3):
            h.add(f"第{i}条", "", 1.0, 0.1)
        assert [e.text for e in h.recent()] == ["第2条", "第1条", "第0条"]
        h.close()

    def test_search(self, tmp_path):
        h = make(tmp_path)
        h.add("把这个 function 改成 async", "", 1.0, 0.1)
        h.add("打开那个文件看一下", "", 1.0, 0.1)
        assert len(h.recent(search="function")) == 1
        assert len(h.recent(search="文件")) == 1
        assert len(h.recent(search="不存在的词")) == 0
        h.close()

    def test_trim_to_max(self, tmp_path):
        """超出上限删最旧的,保留最新的。"""
        h = make(tmp_path, max_entries=5)
        for i in range(12):
            h.add(f"第{i}条", "", 1.0, 0.1)
        assert h.count() == 5
        assert h.recent()[0].text == "第11条"
        h.close()

    def test_delete(self, tmp_path):
        h = make(tmp_path)
        eid = h.add("要删掉的", "", 1.0, 0.1)
        h.add("留下的", "", 1.0, 0.1)
        h.delete(eid)
        assert [e.text for e in h.recent()] == ["留下的"]
        h.close()

    def test_clear(self, tmp_path):
        h = make(tmp_path)
        for i in range(4):
            h.add(f"第{i}条", "", 1.0, 0.1)
        h.clear()
        assert h.count() == 0
        h.close()

    def test_persists_across_open(self, tmp_path):
        h = make(tmp_path)
        h.add("持久化", "", 1.0, 0.1)
        h.close()
        h2 = make(tmp_path)
        assert h2.recent()[0].text == "持久化"
        h2.close()

    def test_zero_audio_rtf(self, tmp_path):
        """除零保护:空音频不能让读历史崩掉。"""
        h = make(tmp_path)
        h.add("x", "", 0.0, 0.1)
        assert h.recent()[0].rtf == 0.0
        h.close()


class TestMaxEntriesChange:
    """改上限要**立刻**生效。

    用户把上限从 2000 改成 100,是希望多余的马上就没了,
    而不是等下次说话写入时才顺带裁剪。
    """

    def test_lowering_trims_immediately(self, tmp_path):
        h = make(tmp_path, max_entries=100)
        for i in range(50):
            h.add(f"第{i}条", "", 1.0, 0.1)
        h.set_max_entries(10)
        assert h.count() == 10
        h.close()

    def test_keeps_newest_when_trimming(self, tmp_path):
        h = make(tmp_path, max_entries=100)
        for i in range(20):
            h.add(f"第{i}条", "", 1.0, 0.1)
        h.set_max_entries(3)
        assert [e.text for e in h.recent()] == ["第19条", "第18条", "第17条"]
        h.close()

    def test_raising_keeps_everything(self, tmp_path):
        h = make(tmp_path, max_entries=5)
        for i in range(5):
            h.add(f"第{i}条", "", 1.0, 0.1)
        h.set_max_entries(1000)
        assert h.count() == 5
        h.close()

    def test_new_limit_applies_to_later_writes(self, tmp_path):
        h = make(tmp_path, max_entries=1000)
        h.set_max_entries(3)
        for i in range(10):
            h.add(f"第{i}条", "", 1.0, 0.1)
        assert h.count() == 3
        h.close()

    def test_zero_is_clamped(self, tmp_path):
        """上限 0 会让每次写入立刻被删掉,等于历史坏了。至少留一条。"""
        h = make(tmp_path, max_entries=100)
        h.add("留着", "", 1.0, 0.1)
        h.set_max_entries(0)
        assert h.count() == 1
        h.close()
