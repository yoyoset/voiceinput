"""单击托盘说话时,焦点要还给"用户真正在用的那个窗口"。

2026-09-24 实测:点托盘图标后前台先后是 Shell_TrayWnd 和
TopLevelWindowForOverflowXamlIsland,这些都不能当成输入目标。
"""

from voiceinput.focus_tracker import SHELL_CLASSES, is_input_target


def test_normal_window_is_a_target():
    assert is_input_target("Chrome_WidgetWin_1", pid=100, own_pid=1)


def test_shell_windows_seen_in_the_probe_are_skipped():
    for cls in ("Shell_TrayWnd", "TopLevelWindowForOverflowXamlIsland"):
        assert cls in SHELL_CLASSES
        assert not is_input_target(cls, pid=100, own_pid=1)


def test_our_own_windows_are_skipped():
    """托盘菜单、设置窗口都是我们自己的 —— 贴进去就是贴进了自己。"""
    assert not is_input_target("Qt6110QWindowIcon", pid=7, own_pid=7)
