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


def test_covered_by_a_normal_window_is_named():
    assert ok(covered_by="chrome.exe:Chrome_WidgetWin_1") == \
        ["被普通窗口压在下面(chrome.exe:Chrome_WidgetWin_1)"]


class TestFirstCover:
    """2026-10-20 现场:带置顶位的徽标沉在第 161 位,上面压着微信/Chrome 等普通窗口。"""

    @staticmethod
    def w(topmost=False, visible=True, cloaked=0, own=False):
        return window_state.Above(topmost=topmost, visible=visible, cloaked=cloaked, own=own)

    def test_only_topmost_above_is_normal(self):
        assert window_state.first_cover([self.w(topmost=True), self.w(topmost=True)]) is None

    def test_nothing_above_is_normal(self):
        assert window_state.first_cover([]) is None

    def test_visible_normal_window_above_means_sunk(self):
        above = [self.w(topmost=True), self.w(visible=False), self.w()]
        assert window_state.first_cover(above) == 2

    def test_invisible_windows_do_not_count(self):
        """z 序前面大量是不可见的辅助窗口,现场光徽标前面就有十几个。"""
        assert window_state.first_cover([self.w(visible=False)] * 20) is None

    def test_cloaked_windows_do_not_count(self):
        """IsWindowVisible 为真但被 DWM 遮住(别的虚拟桌面等),其实看不见。现场有好几个。"""
        assert window_state.first_cover([self.w(cloaked=1), self.w(cloaked=2)]) is None

    def test_our_own_windows_do_not_count(self):
        """自己弹的菜单/设置窗口在前面,不能因此把徽标顶上去盖住它们。"""
        assert window_state.first_cover([self.w(own=True)]) is None
