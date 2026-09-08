"""历史记不记、记多少。

一条不能改的行为:**关掉记录不删已有记录**。用户想的是"以后别记了",
不是"把过去也抹掉"。真要清空,界面上有单独的按钮,那是个需要确认的
破坏性操作。

另一条:**写历史失败不该影响这次听写**。文字已经粘出去了,记不下来是个
次要问题,不能因此弹错误盖掉成功的结果。
"""

import pytest

from voiceinput.config import Config
from voiceinput.history_host import HistoryHost


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """历史库默认落在程序目录旁边,测试里改到临时目录。

    **这个 fixture 一开始是坏的**:它 patch 了 `app_dir`,而路径是
    导入时算好的常量,拦不住 —— 于是测试往项目根目录的真实
    history.db 里写了两条数据。`default_path()` 改成函数之后才拦得住。
    """
    monkeypatch.setattr("voiceinput.history.app_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def host(qapp, in_tmp):
    h = HistoryHost(Config())
    yield h
    h.close()


class TestSwitch:
    def test_enabled_by_default(self, host):
        assert host.current is not None

    def test_starts_closed_when_disabled(self, qapp, in_tmp):
        cfg = Config()
        cfg.history.enabled = False
        h = HistoryHost(cfg)
        assert h.current is None

    def test_turning_off_closes_it(self, host):
        cfg = Config()
        cfg.history.enabled = False
        host.apply(cfg)
        assert host.current is None

    def test_turning_off_does_not_delete_past_entries(self, host, in_tmp):
        """**关掉不等于抹掉。**"""
        host.add("说过的一句话", "", 1.0, 0.1)
        db_file = in_tmp / "history.db"
        cfg = Config()
        cfg.history.enabled = False
        host.apply(cfg)
        assert db_file.exists()

        cfg.history.enabled = True
        host.apply(cfg)
        assert [e.text for e in host.current.recent()] == ["说过的一句话"]

    def test_announces_the_new_object(self, host):
        """换了对象(或者没有对象了),界面得跟着换 ——
        否则历史页会一直显示着一个已经关掉的库。"""
        seen = []
        host.changed.connect(seen.append)
        cfg = Config()
        cfg.history.enabled = False
        host.apply(cfg)
        assert seen == [None]


class TestNoWork:
    def test_same_config_changes_nothing(self, host):
        seen = []
        host.changed.connect(seen.append)
        before = host.current
        host.apply(Config())
        assert host.current is before
        assert seen == []

    def test_unrelated_change_changes_nothing(self, host):
        seen = []
        host.changed.connect(seen.append)
        cfg = Config()
        cfg.ui.theme = "dark"
        host.apply(cfg)
        assert seen == []


class TestMaxEntries:
    def test_lowering_the_cap_takes_effect_now(self, host):
        """上限调小了要立刻生效,不能等到下次写入才裁剪 ——
        否则用户关掉界面之前看不到任何变化,会以为设置没生效。"""
        for i in range(5):
            host.add(f"第 {i} 条", "", 1.0, 0.1)
        cfg = Config()
        cfg.history.max_entries = 2
        host.apply(cfg)
        assert host.current.count() == 2


class TestAdd:
    def test_add_while_disabled_is_a_noop(self, qapp, in_tmp):
        cfg = Config()
        cfg.history.enabled = False
        h = HistoryHost(cfg)
        h.add("不该被记下", "", 1.0, 0.1)      # 不抛就算过
        assert h.current is None

    def test_write_failure_does_not_propagate(self, host, monkeypatch):
        """**文字已经粘出去了。** 记不下来不能变成一次用户可见的失败。"""
        monkeypatch.setattr(host.current, "add",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("磁盘满了")))
        host.add("一句话", "", 1.0, 0.1)       # 不抛就算过
