"""前台窗口判断——只在 Windows 上有意义,其它平台明确返回 None。

这个模块本身很薄,真正的行为(GetForegroundWindow 到底靠不靠谱)只能在
真实 Windows 上验证,单元测试只管"这层包装没写错"。
"""

import sys

from voiceinput.foreground import foreground_window


def test_非windows平台返回none(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert foreground_window() is None


def test_windows平台调用系统api(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    import ctypes

    monkeypatch.setattr(
        ctypes, "windll",
        type("Fake", (), {"user32": type("U", (), {
            "GetForegroundWindow": staticmethod(lambda: 12345),
        })()})(),
        raising=False,
    )
    assert foreground_window() == 12345
