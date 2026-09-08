"""闲着的时候状态栏该显示什么。

这段逻辑原来在五个地方各写了一遍(引擎加载完、识别完、错误提示过期、
配置变更、暂停切换),改一处就得记得改另外四处。统一成
`_current_idle_state` 之后,这里钉住它的三个分支。

"什么时候显示"和"显示到哪几处"不在这里 —— 那归 StatusPresenter,
见 test_status.py。
"""

from voiceinput.app import App


class FakeTray:
    def __init__(self, paused: bool = False) -> None:
        self.is_paused = paused


class FakeHotkeys:
    def summary(self) -> str:
        return "Ctrl + Alt + Space 说话粘贴"


class FakeEngine:
    def __init__(self, ready: bool = True) -> None:
        self.is_ready = ready


class FakeApp:
    """只带这段判断所需字段的替身,复用 App 上的真实方法。"""

    def __init__(self, paused: bool = False) -> None:
        self.engine = FakeEngine()
        self.hotkeys = FakeHotkeys()
        self.tray = FakeTray(paused)

    _current_idle_state = App._current_idle_state


class TestIdleStateIsComputedInOnePlace:
    def test_ready(self):
        assert FakeApp()._current_idle_state()[:2] == ("ready", "就绪")

    def test_shows_the_hotkeys_when_ready(self):
        """就绪时要顺手告诉用户按哪个键 —— 否则改了热键之后没处查。"""
        assert "Ctrl" in FakeApp()._current_idle_state()[2]

    def test_engine_not_ready(self):
        app = FakeApp()
        app.engine.is_ready = False
        assert app._current_idle_state()[:2] == ("error", "模型未加载")

    def test_paused(self):
        assert FakeApp(paused=True)._current_idle_state()[:2] == ("loading", "已暂停")

    def test_paused_says_how_to_resume(self):
        """只说"已暂停"而不说怎么恢复,等于把人晾在那儿。"""
        assert "托盘" in FakeApp(paused=True)._current_idle_state()[2]

    def test_paused_takes_priority_over_engine_state(self):
        """两个条件都成立时,暂停优先 —— 它是用户显式设置的。"""
        app = FakeApp(paused=True)
        app.engine.is_ready = False
        assert app._current_idle_state()[:2] == ("loading", "已暂停")
