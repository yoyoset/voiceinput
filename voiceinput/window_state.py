"""一个我们自己的窗口,在 Windows 眼里到底还在不在屏幕上。

**为什么要问 Windows 而不是问 Qt**:Qt 的 `isVisible()` 只记得"我上次叫它
显示过",窗口被系统从外面藏掉时它并不知道。2026-09-24 的实际故障:
悬浮麦克风不见了,设置里那个勾还勾着 —— 再勾一次没用(Qt 认为它本来就显示着,
什么都不做),只能先取消再勾上。

外面能把它藏掉的途径不止一种,手上没有哪一种的实测证据,所以都查:

- `IsWindowVisible` 为假 —— 窗口被 hide 掉了
- `IsIconic` —— 被最小化(比如"显示桌面")
- DWM cloaked —— 被系统"遮住"但不算隐藏,切换虚拟桌面时别的桌面上的窗口就是这样
- 不在任何一块屏幕上 —— 拔了外接屏、改了分辨率

查出来的原因会写进日志,下次再出现就知道到底是哪一种了。
"""

from __future__ import annotations

import sys

# DwmGetWindowAttribute 的 DWMWA_CLOAKED
_DWMWA_CLOAKED = 14


def problems(*, visible: bool, iconic: bool, cloaked: int, on_screen: bool) -> list[str]:
    """把系统报告的窗口状态翻成"哪里不对"。空列表 = 一切正常。纯函数,便于测。"""
    found = []
    if not visible:
        found.append("被隐藏")
    if iconic:
        found.append("被最小化")
    if cloaked:
        # 1 = 应用自己, 2 = 系统外壳(虚拟桌面切换等), 4 = 继承
        found.append(f"被系统遮蔽(cloaked={cloaked})")
    if not on_screen:
        found.append("不在任何屏幕上")
    return found


def probe(hwnd: int) -> tuple[bool, bool, int] | None:
    """问 Windows:(可见, 最小化, cloaked)。非 Windows 返回 None = 不判断。"""
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    visible = bool(user32.IsWindowVisible(hwnd))
    iconic = bool(user32.IsIconic(hwnd))
    cloaked = wt.DWORD(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wt.HWND(hwnd), _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    except OSError:
        cloaked.value = 0   # 没有 DWM(极老系统/远程会话的某些情况)就当没遮
    return visible, iconic, int(cloaked.value)
