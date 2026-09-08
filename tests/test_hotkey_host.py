"""热键的注册与注销。

以前"配置里的热键有没有变"这个判断写在 App 的配置分发里 ——
等于让 App 替热键这一摊记着它自己的旧值。每加一个热键相关的配置项,
那边的 if 就得跟着改一次,漏改的表现是**改了设置没生效,而且不报错**。

现在 `apply()` 自己比对自己的旧值。
"""

import pytest

from voiceinput.config import Config
from voiceinput.hotkey_host import HotkeyHost


class FakeManager:
    """替身 HotkeyManager —— 真的装钩子会影响正在用电脑的人。"""

    made: list = []

    def __init__(self, bindings, mode, on_start, on_stop, on_upgrade, on_error):
        self.bindings = dict(bindings)
        self.mode = mode
        self.on_start = on_start
        self.started = False
        self.stopped = False
        FakeManager.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture
def host(qapp, monkeypatch):
    FakeManager.made = []
    monkeypatch.setattr("voiceinput.hotkey_host.HotkeyManager", FakeManager)
    # 探测要问系统,测试里不该依赖这台机器装了什么
    monkeypatch.setattr("voiceinput.conflict.taken_by_another_app", lambda spec: False)
    h = HotkeyHost()
    yield h
    h.stop()


class TestApply:
    def test_registers_on_first_apply(self, host):
        host.apply(Config())
        assert len(FakeManager.made) == 1
        assert FakeManager.made[0].started

    def test_same_config_does_not_re_register(self, host):
        """**没变就什么都不做。**

        重复注册意味着先 stop 再 start —— 中间那一小段时间按热键是没反应的,
        而配置保存是防抖后批量发出来的,一次改动会走好几遍这条路。
        """
        cfg = Config()
        host.apply(cfg)
        host.apply(Config())          # 内容相同的另一个对象
        assert len(FakeManager.made) == 1

    def test_changed_binding_re_registers(self, host):
        host.apply(Config())
        cfg = Config()
        cfg.hotkey.paste = "<ctrl>+<alt>+j"
        host.apply(cfg)
        assert len(FakeManager.made) == 2
        assert FakeManager.made[0].stopped, "换绑之前要先把旧的卸掉"

    def test_changed_mode_re_registers(self, host):
        """触发方式也是热键这一摊的事 —— 漏掉它的表现是
        "改成了按一下开始,却还是按住说话",而且不报错。"""
        host.apply(Config())
        cfg = Config()
        cfg.hotkey.mode = "toggle"
        host.apply(cfg)
        assert len(FakeManager.made) == 2
        assert FakeManager.made[1].mode == "toggle"

    def test_unrelated_config_change_does_not_touch_hotkeys(self, host):
        host.apply(Config())
        cfg = Config()
        cfg.ui.theme = "dark"
        cfg.engine.num_threads = 12
        host.apply(cfg)
        assert len(FakeManager.made) == 1


class TestFailure:
    def test_register_failure_is_announced(self, host, monkeypatch):
        """注册失败必须说出来 —— 否则表现是"按热键完全没反应"而没有任何线索。"""
        from voiceinput.hotkey import HotkeyError

        def boom(*a, **k):
            raise HotkeyError("写法不合法")

        monkeypatch.setattr("voiceinput.hotkey_host.HotkeyManager", boom)
        seen = []
        host.registerFailed.connect(seen.append)
        host.apply(Config())
        assert seen and "写法不合法" in seen[0]

    def test_retry_after_failure_actually_retries(self, host, monkeypatch):
        """失败之后没记下任何绑定,所以下次 apply 不该被"没变"挡掉。"""
        from voiceinput.hotkey import HotkeyError

        monkeypatch.setattr("voiceinput.hotkey_host.HotkeyManager",
                            lambda *a, **k: (_ for _ in ()).throw(HotkeyError("x")))
        host.apply(Config())
        monkeypatch.setattr("voiceinput.hotkey_host.HotkeyManager", FakeManager)
        host.apply(Config())
        assert len(FakeManager.made) == 1


class TestSummary:
    def test_empty_before_registering(self, host):
        assert host.summary() == ""

    def test_describes_both_actions(self, host):
        host.apply(Config())
        text = host.summary()
        assert "说话粘贴" in text and "粘贴并发送" in text

    def test_follows_the_registered_binding_not_the_config(self, host):
        """注册失败时摘要不该显示那个没生效的组合 ——
        状态栏说"按 X",按下去却没反应,比不说更坏。"""
        host.apply(Config())
        before = host.summary()
        cfg = Config()
        cfg.hotkey.paste = "<ctrl>+<alt>+j"
        host.apply(cfg)
        assert host.summary() != before


class TestConflictIsAnnounced:
    """热键被占用**必须主动说出来**。

    按下去两个程序会一起动,而且不会有任何报错 —— 用户只会觉得
    "这软件怪怪的",不会想到去翻日志,更不会想到去设置页点"检查占用"。
    以前这件事只写日志,等于没说。
    """

    def taken(self, monkeypatch, *specs):
        wanted = set(specs)
        monkeypatch.setattr("voiceinput.conflict.taken_by_another_app",
                            lambda spec: spec in wanted)

    def test_announced_when_occupied(self, host, monkeypatch):
        cfg = Config()
        self.taken(monkeypatch, cfg.hotkey.paste)
        seen = []
        host.conflictDetected.connect(seen.append)
        host.apply(cfg)
        assert seen and "粘贴文字" in seen[0]

    def test_silent_when_all_free(self, host, monkeypatch):
        """没冲突就别说话 —— 每次启动弹一句"一切正常"只会让人学会无视提示。"""
        self.taken(monkeypatch)
        seen = []
        host.conflictDetected.connect(seen.append)
        host.apply(Config())
        assert seen == []

    def test_both_occupied_are_named_together(self, host, monkeypatch):
        cfg = Config()
        self.taken(monkeypatch, cfg.hotkey.paste, cfg.hotkey.paste_and_send)
        seen = []
        host.conflictDetected.connect(seen.append)
        host.apply(cfg)
        assert "粘贴文字" in seen[0] and "粘贴并发送" in seen[0]

    def test_summary_marks_the_occupied_one(self, host, monkeypatch):
        """状态栏说"按 X"而按下去两个程序一起动,比不说更坏。"""
        cfg = Config()
        self.taken(monkeypatch, cfg.hotkey.paste)
        host.apply(cfg)
        text = host.summary()
        assert "被占用" in text
        assert text.count("被占用") == 1, "只有一个被占,不该两个都标"

    def test_summary_is_clean_when_free(self, host, monkeypatch):
        self.taken(monkeypatch)
        host.apply(Config())
        assert "被占用" not in host.summary()

    def test_marks_are_recomputed_on_rebind(self, host, monkeypatch):
        """换成一个空闲组合之后,记号要跟着消失 ——
        留着过期的"被占用"比没有更糟。"""
        cfg = Config()
        self.taken(monkeypatch, cfg.hotkey.paste)
        host.apply(cfg)
        assert "被占用" in host.summary()

        self.taken(monkeypatch)          # 现在什么都不占
        cfg2 = Config()
        cfg2.hotkey.paste = "<ctrl>+<alt>+j"
        host.apply(cfg2)
        assert "被占用" not in host.summary()
