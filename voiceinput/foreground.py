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


def activate_window(hwnd: int) -> bool:
    """把前台还给 `hwnd`。返回系统是否接受了这个请求。

    **不是立即生效的**:2026-09-24 实测调用返回 1 之后马上 GetForegroundWindow
    得到的是 0,要过一小会儿才变成目标窗口 —— 调用方要等它落定再做事,
    见 `App._toggle_from_tray`。

    Windows 平时不让后台程序抢前台;这里能成功是因为用户刚点了我们的
    托盘图标,系统在那一刻授权了图标的主人。
    """
    if sys.platform != "win32" or not hwnd:
        return False
    import ctypes

    return bool(ctypes.windll.user32.SetForegroundWindow(hwnd))
