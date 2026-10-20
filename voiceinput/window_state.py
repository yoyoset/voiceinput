"""一个我们自己的窗口,在 Windows 眼里到底还在不在屏幕上。

**为什么要问 Windows 而不是问 Qt**:Qt 的 `isVisible()` 只记得"我上次叫它
显示过",窗口被系统从外面藏掉时它并不知道。2026-09-24 的实际故障:
悬浮麦克风不见了,设置里那个勾还勾着 —— 再勾一次没用(Qt 认为它本来就显示着,
什么都不做),只能先取消再勾上。

外面能把它藏掉的途径不止一种,手上没有哪一种的实测证据,所以都查:

- `IsWindowVisible` 为假 —— 窗口被 hide 掉了
- `IsIconic` —— 被最小化(比如"显示桌面"。2026-10-17 日志里实际抓到过 12 次)
- DWM cloaked —— 被系统"遮住"但不算隐藏,切换虚拟桌面时别的桌面上的窗口就是这样
- 不在任何一块屏幕上 —— 拔了外接屏、改了分辨率
- **被普通窗口压在下面** —— 2026-10-20 实际抓到,见 `first_cover`

查出来的原因会写进日志,下次再出现就知道到底是哪一种了。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

# DwmGetWindowAttribute 的 DWMWA_CLOAKED
_DWMWA_CLOAKED = 14


def problems(*, visible: bool, iconic: bool, cloaked: int, on_screen: bool,
             covered_by: str | None = None) -> list[str]:
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
    if covered_by:
        found.append(f"被普通窗口压在下面({covered_by})")
    return found


@dataclass(frozen=True)
class Above:
    """z 序里排在我们前面的一个窗口,只留判断要用的几项。"""
    topmost: bool
    visible: bool
    cloaked: int
    own: bool          # 是不是我们自己进程的


def first_cover(above: list[Above]) -> int | None:
    """置顶窗口前面出现了**可见的普通窗口** = 置顶档乱了。返回第一个这样的下标。纯函数。

    **2026-10-20 实测的现场:** 徽标 IsWindowVisible 真、没最小化、没遮蔽、在屏幕内,
    `WS_EX_TOPMOST` 位也还在,可 z 序排在第 161 位,上面压着微信、Chrome 这些最大化的
    普通窗口,截屏看不到它。同一时刻 magpie 的置顶窗口、explorer 自己的副屏任务栏
    也带着置顶位沉在普通窗口下面 —— 是系统级的错乱,触发源没抓到。

    正常情况下置顶窗口前面只会有置顶窗口,所以判据就是这条规矩本身,
    不用"和我相不相交"之类的猜测。两种跳过:

    - **被遮蔽的**:IsWindowVisible 为真但其实看不见(别的虚拟桌面上的窗口、
      系统的各种隐形窗口),现场就有好几个。
    - **我们自己进程的**:右键菜单之类是我们自己弹的,不能因为它把徽标又顶上去
      盖住菜单。真沉下去的时候压着的是别人的窗口,少看这几个也认得出来。
    """
    for i, w in enumerate(above):
        if w.visible and not w.topmost and not w.cloaked and not w.own:
            return i
    return None


def probe(hwnd: int) -> tuple[bool, bool, int] | None:
    """问 Windows:(可见, 最小化, cloaked)。非 Windows 返回 None = 不判断。"""
    if sys.platform != "win32":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    visible = bool(user32.IsWindowVisible(hwnd))
    iconic = bool(user32.IsIconic(hwnd))
    return visible, iconic, _cloaked(hwnd)


def covering_window(hwnd: int) -> str | None:
    """有没有普通窗口排在我们前面。有就返回它的"进程名:类名"(写日志用),没有返回 None。

    沿 z 序往前走(GW_HWNDPREV),判断交给 `first_cover`。正常时徽标排在很前面,
    往前只有十几个窗口;沉下去时碰到第一个就停。3 秒一次,开销可以忽略。
    """
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wt

    u32 = ctypes.windll.user32
    u32.GetWindow.restype = wt.HWND
    u32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    u32.GetWindowLongW.restype = ctypes.c_long
    own = os.getpid()
    cur = u32.GetWindow(hwnd, 3)                         # GW_HWNDPREV
    while cur:
        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(cur, ctypes.byref(pid))
        h = int(cur)
        above = Above(
            topmost=bool(u32.GetWindowLongW(cur, -20) & 0x8),   # GWL_EXSTYLE & WS_EX_TOPMOST
            visible=bool(u32.IsWindowVisible(cur)),
            cloaked=_cloaked(h),
            own=pid.value == own,
        )
        if first_cover([above]) is not None:
            return _label(h, pid.value)
        cur = u32.GetWindow(cur, 3)
    return None


def raise_topmost(hwnd: int) -> bool:
    """重新插回置顶档的最前面。**不激活、不挪位置、不改大小。**

    2026-10-20 在现场实测:一次调用,徽标 z 序从 161 回到 16,WindowFromPoint
    打回到它自己,前台窗口没变(不抢焦点),1.5 分钟后还在 16。
    `WS_EX_TOPMOST` 位本来就置着的情况下照样管用。
    """
    if sys.platform != "win32":
        return False
    import ctypes
    import ctypes.wintypes as wt

    flags = 0x0001 | 0x0002 | 0x0010          # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    return bool(ctypes.windll.user32.SetWindowPos(
        wt.HWND(hwnd), wt.HWND(-1), 0, 0, 0, 0, flags))   # HWND_TOPMOST


def _cloaked(hwnd: int) -> int:
    import ctypes
    import ctypes.wintypes as wt

    value = wt.DWORD(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wt.HWND(hwnd), _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    except OSError:
        return 0    # 没有 DWM(极老系统/远程会话的某些情况)就当没遮
    return int(value.value)


def _label(hwnd: int, pid: int) -> str:
    """进程名:类名。拿不到进程名就写 "?" —— 只是日志用的,用来追是谁压上来的。"""
    import ctypes
    import ctypes.wintypes as wt

    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    cls = ctypes.create_unicode_buffer(128)
    u32.GetClassNameW(wt.HWND(hwnd), cls, 128)
    name = "?"
    handle = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        buf = ctypes.create_unicode_buffer(512)
        size = wt.DWORD(512)
        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            name = buf.value.rsplit("\\", 1)[-1]
        k32.CloseHandle(handle)
    return f"{name}:{cls.value}"
