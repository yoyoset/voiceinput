"""状态显示的守卫。

**过期的异步回调不能覆盖当前状态。** 引擎加载完成、错误提示过期、
配置保存完 —— 这些都可能在用户已经重新开始录音之后才到,
直接 set 就会把"正在聆听"覆盖成"就绪",而录音其实还在继续。

以前这套逻辑挂在 App 上,只能用一个借了 App 方法的 FakeApp 来测。
现在 StatusPresenter 是个独立对象,直接测真的。
"""

import pytest

from voiceinput.ui.status import (
    ERROR_LINGER_MS,
    STARTUP_WARNING_DELAY_MS,
    StatusPresenter,
)


class FakeTray:
    def __init__(self, paused=False):
        self.is_paused = paused
        self.states = []

    def set_state(self, state, text):
        self.states.append((state, text))


class FakeWindow:
    def __init__(self):
        self.statuses = []

    def set_status(self, state, text, detail=""):
        self.statuses.append((state, text, detail))


class FakeBadge:
    def __init__(self):
        self.states = []

    def set_state(self, state):
        self.states.append(state)


class FakeOverlay:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def show_error(self, message, ms):
        self.errors.append(message)

    def show_warning(self, message, ms):
        self.warnings.append((message, ms))


class Rig:
    def __init__(self, qapp, paused=False, idle=True):
        self.tray = FakeTray(paused)
        self.window = FakeWindow()
        self.badge = FakeBadge()
        self.overlay = FakeOverlay()
        self.idle = idle
        self.presenter = StatusPresenter(
            self.tray, self.window, self.badge, self.overlay,
            idle_state=lambda: ("ready", "就绪", "Ctrl + Alt + Space"),
            is_idle=lambda: self.idle,
        )


@pytest.fixture
def rig(qapp):
    r = Rig(qapp)
    yield r
    r.presenter.stop()


class TestFanout:
    """三个地方必须说同一件事。

    各自 set 的话,早晚会出现托盘写着"就绪"而悬浮麦克风还亮着录音色。
    """

    def test_all_three_get_told(self, rig):
        rig.presenter.show("recording", "正在聆听", "说吧")
        assert rig.tray.states == [("recording", "正在聆听")]
        assert rig.window.statuses == [("recording", "正在聆听", "说吧")]
        assert rig.badge.states == ["recording"]

    def test_paused_overrides_the_badge(self, qapp):
        """暂停时悬浮麦克风要显示暂停,不管传进来的是什么状态 ——
        否则它会亮着"就绪"色,而按热键其实没反应。"""
        r = Rig(qapp, paused=True)
        r.presenter.show("ready", "就绪")
        assert r.badge.states == ["paused"]
        r.presenter.stop()


class TestRefreshGuard:
    def test_refresh_when_idle(self, rig):
        rig.presenter.refresh()
        assert rig.tray.states == [("ready", "就绪")]

    def test_refresh_does_nothing_while_busy(self, rig):
        """**核心断言。** 正在录音/识别时刷新必须是空操作。"""
        rig.idle = False
        rig.presenter.refresh()
        assert rig.tray.states == []

    def test_show_idle_bypasses_the_guard(self, rig):
        """暂停/恢复是用户的显式操作,即便正在录音也应该如实反映。"""
        rig.idle = False
        rig.presenter.show_idle()
        assert rig.tray.states == [("ready", "就绪")]


class TestFailure:
    def test_failure_is_visible_everywhere(self, rig):
        rig.presenter.fail("只录到静音")
        assert rig.tray.states == [("error", "出错了")]
        assert rig.overlay.errors == ["只录到静音"]

    def test_second_failure_restarts_one_timer(self, rig):
        """**用同一个定时器并重启,不能每次起一个新的。**

        4.2 秒内失败两次就会有两个定时器在跑,先到的那个把状态重置成
        "就绪",而第二次失败的错误还挂在界面上;更糟的是这期间若已
        重新开始录音,过期定时器会在录音中途把状态改成"就绪"。
        """
        rig.presenter.fail("第一次")
        first = rig.presenter._reset_timer
        rig.presenter.fail("第二次")
        assert rig.presenter._reset_timer is first
        assert first.isActive()

    def test_timer_actually_restores(self, qapp, rig):
        """错误提示过期后要真的回到常态。"""
        from PySide6.QtCore import QEventLoop, QTimer

        rig.presenter._reset_timer.setInterval(30)
        rig.presenter.fail("坏了")
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()
        assert ("ready", "就绪") in rig.tray.states

    def test_linger_outlasts_the_overlay(self):
        """状态栏上的错误要比悬浮条(4000ms)停留得久一点,
        否则会出现状态栏已经"就绪"而悬浮条还红着。"""
        assert ERROR_LINGER_MS > 4000

    def test_stop_cancels_the_timer(self, rig):
        rig.presenter.fail("坏了")
        rig.presenter.stop()
        assert not rig.presenter._reset_timer.isActive()


class TestWarnLater:
    """启动阶段"程序知道、用户不知道"的事,必须主动弹出来。

    用它说的两件事 —— 设备被悄悄换掉了、热键被别的程序占着 ——
    **都不会报任何错**。不主动说就等于没有。
    """

    def pump(self, ms=400):
        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def test_warning_actually_appears(self, qapp, rig):
        rig.overlay.warnings = []
        rig.presenter.warn_later("热键被占用了", 9000)
        self.pump(STARTUP_WARNING_DELAY_MS + 300)
        assert rig.overlay.warnings == [("热键被占用了", 9000)]

    def test_it_is_delayed(self, qapp, rig):
        """**不能立刻弹。** 启动那一刻界面还在铺,这时候弹会被盖掉。"""
        rig.overlay.warnings = []
        rig.presenter.warn_later("晚点说", 5000)
        self.pump(50)
        assert rig.overlay.warnings == [], "弹得太早会被启动中的界面盖掉"

    def test_two_warnings_do_not_overwrite_each_other(self, qapp, rig):
        """**悬浮条只有一个。** 同时弹两条的话后一条把前一条顶掉,
        用户只看得见其中一条 —— 而这两条恰恰都是他需要知道的。

        (第一版就是这样,而且显示顺序连稳定都不稳定。)
        """
        rig.overlay.warnings = []
        rig.presenter.warn_later("先说这条", 300)
        rig.presenter.warn_later("再说这条", 300)

        self.pump(STARTUP_WARNING_DELAY_MS + 150)
        assert [t for t, _ in rig.overlay.warnings] == ["先说这条"], "第二条不该抢在前面"

        self.pump(1000)
        assert [t for t, _ in rig.overlay.warnings] == ["先说这条", "再说这条"]

    def test_linger_is_caller_chosen(self, qapp, rig):
        """两种警告该停留多久不一样:设备提示看一眼就够,
        热键冲突要给人时间读懂并决定要不要去改。"""
        rig.overlay.warnings = []
        rig.presenter.warn_later("甲", 6000)
        self.pump(STARTUP_WARNING_DELAY_MS + 300)
        assert rig.overlay.warnings == [("甲", 6000)]

    def test_delay_outlasts_window_setup(self):
        assert STARTUP_WARNING_DELAY_MS >= 1000
