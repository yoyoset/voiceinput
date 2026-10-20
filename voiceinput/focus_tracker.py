"""记住"用户最近一次真正在用的窗口"——给"单击托盘图标说话"用。

**为什么需要它**:点悬浮麦克风不抢焦点,可点托盘图标会。2026-09-24 实测
(scratchpad 里的 tray_focus_probe):点一下托盘里的图标,前台窗口先后变成
`Shell_TrayWnd`(任务栏)和 `TopLevelWindowForOverflowXamlIsland`(托盘溢出框)。
这时候直接开始录音,记下的"目标窗口"就是任务栏;再点一下结束时前台又是
任务栏/溢出框 —— 结果要么粘进任务栏,要么被 Delivery 以"目标窗口换了"拦下,
每一句都得自己手动粘。

同一次实测也确认了退路是通的:点托盘时 Windows 允许图标的主人抢前台,
`SetForegroundWindow(之前那个记事本)` 返回 1,约 300ms 内记事本就回到了前台
(调用刚返回那一刻 GetForegroundWindow 是 0,不是立即生效的)。

所以这里订阅"前台窗口变了"的系统事件,把任务栏、托盘溢出框和我们自己的
窗口都跳过,剩下的最后一个就是用户要输入的地方。
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QObject

log = logging.getLogger("voiceinput")

# 点任务栏/托盘时临时拿到前台的外壳窗口。都不是"用户在往里打字的地方"。
SHELL_CLASSES = frozenset({
    "Shell_TrayWnd",                          # 主任务栏
    "Shell_SecondaryTrayWnd",                 # 副屏任务栏
    "NotifyIconOverflowWindow",               # Win10 托盘溢出框
    "TopLevelWindowForOverflowXamlIsland",    # Win11 托盘溢出框(实测)
    "XamlExplorerHostIslandWindow",           # Win11 任务栏上的各种弹出层
})

_EVENT_SYSTEM_FOREGROUND = 0x0003
_WINEVENT_OUTOFCONTEXT = 0x0000


def is_input_target(class_name: str, pid: int, own_pid: int) -> bool:
    """这个窗口能不能当"用户要输入的地方"。纯函数,便于测。"""
    if pid == own_pid:
        return False       # 我们自己的窗口(设置页、托盘菜单)
    return class_name not in SHELL_CLASSES


class FocusTracker(QObject):
    """订阅前台切换,记住最后一个"真正的"窗口。非 Windows 上什么都不做。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._last: int | None = None
        self._hook = None
        self._proc = None      # 回调对象必须一直有人引用着,否则被回收后系统回调进野指针

    @property
    def last_target(self) -> int | None:
        return self._last

    def start(self) -> None:
        if sys.platform != "win32" or self._hook:
            return
        import ctypes
        import ctypes.wintypes as wt

        user32 = ctypes.windll.user32
        own_pid = os.getpid()
        proto = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG,
                                   wt.LONG, wt.DWORD, wt.DWORD)

        def on_foreground(_hook, _event, hwnd, *_rest) -> None:
            if not hwnd:
                return
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if is_input_target(cls.value, pid.value, own_pid):
                self._last = hwnd

        self._proc = proto(on_foreground)
        # OUTOFCONTEXT:回调由本线程(Qt 主线程)的消息循环投递,不需要注入 DLL,
        # 也不会在别的线程上跑。
        self._hook = user32.SetWinEventHook(
            _EVENT_SYSTEM_FOREGROUND, _EVENT_SYSTEM_FOREGROUND, 0, self._proc,
            0, 0, _WINEVENT_OUTOFCONTEXT)
        if not self._hook:
            log.warning("前台窗口跟踪没挂上,单击托盘说话时焦点可能回不到原窗口")
        # 启动那一刻的前台窗口也算一个候选,免得第一次点托盘时一无所知
        on_foreground(None, 0, user32.GetForegroundWindow())

    def stop(self) -> None:
        if self._hook:
            import ctypes

            ctypes.windll.user32.UnhookWinEvent(self._hook)
            self._hook = None
