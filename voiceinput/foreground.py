"""按下热键那一刻前台是谁——用来判断粘贴时窗口是不是已经被换掉了。

**只有 Windows 有这个概念。** 其它平台返回 `None`,这里 `None` 的语义是
"不知道/不判断",不是"没有窗口"——调用方拿它跟另一次调用的结果比较,
两次都是 `None` 时会被当成"没变",不会在不支持这个 API 的平台上把本来
正常的粘贴也拦下来。
"""

from __future__ import annotations

import sys


def foreground_window() -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.windll.user32.GetForegroundWindow()
