"""退出。

2026-09-24 实际故障:点了「退出」,日志有"退出",进程却一直活着,
"识别中…"的提示条也一直挂在桌面上。没抓到是哪一步,所以钉住两条:
一步出错不能连累后面的,最后一定真的结束事件循环。
"""

from __future__ import annotations

from voiceinput.app import App


class Part:
    def __init__(self, log, name, boom=False):
        self._log, self._name, self._boom = log, name, boom

    def __getattr__(self, attr):
        def call(*a, **k):
            self._log.append(f"{self._name}.{attr}")
            if self._boom:
                raise RuntimeError("boom")
        return call


class FakeApp:
    def __init__(self, boom: str = ""):
        self.log: list[str] = []
        for name in ("window", "hotkeys", "cancel_key", "focus", "status", "session",
                     "engine", "history", "overlay", "badge", "tray", "qapp"):
            setattr(self, name, Part(self.log, name, boom=(name == boom)))

    shutdown = App.shutdown


def test_正常退出最后结束事件循环():
    app = FakeApp()
    app.shutdown()
    assert app.log[-1] == "qapp.exit"
    assert "overlay.hide" in app.log, "挂着的「识别中…」要一起收掉"


def test_中间一步出错也照样退出():
    """以前是一串裸调用:热键那步一抛异常,后面的 quit 就没了,
    打包版又没有控制台,什么都看不见。"""
    app = FakeApp(boom="hotkeys")
    app.shutdown()
    assert app.log[-1] == "qapp.exit"
    assert "tray.hide" in app.log


def test_用的是不会被拒绝的exit():
    """Qt 6 的 quit() 是请求,可以被拒;exit() 不会。"""
    app = FakeApp()
    app.shutdown()
    assert "qapp.quit" not in app.log
