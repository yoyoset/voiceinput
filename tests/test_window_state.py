"""悬浮麦克风"还在不在屏幕上"的判断。

2026-09-24 实际故障:它凭空消失,设置里的勾还勾着,只能取消再勾上。
Qt 的 isVisible() 不知道窗口被系统从外面藏掉了,所以要问 Windows。
"""

from voiceinput import window_state


def ok(**kw):
    base = dict(visible=True, iconic=False, cloaked=0, on_screen=True)
    base.update(kw)
    return window_state.problems(**base)


def test_all_good_means_no_problem():
    assert ok() == []


def test_each_way_of_disappearing_is_named():
    assert ok(visible=False) == ["被隐藏"]
    assert ok(iconic=True) == ["被最小化"]
    assert ok(cloaked=2) == ["被系统遮蔽(cloaked=2)"]
    assert ok(on_screen=False) == ["不在任何屏幕上"]


def test_several_at_once_are_all_reported():
    """日志要能告诉我们到底是哪一种 —— 不能只报第一个。"""
    assert len(ok(visible=False, iconic=True)) == 2
