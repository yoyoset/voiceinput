"""历史「重新粘贴」必须先把主窗口藏起来。

原来的实现直接发 Ctrl+V:而用户是点主窗口里的按钮触发的,此刻前台窗口
就是 VoiceInput 自己,文字会粘进它自己的历史搜索框。
提示文案当时写的是"先切到目标窗口再操作"—— 可切走了就点不到按钮,
自相矛盾,那个功能按文案描述的方式根本用不了。

这些测试原来要拼一个带 window/output/overlay 三个替身的 FakeApp 才跑得起来。
`Delivery` 拆出来之后,它只认识一个"让出焦点"的回调,替身也就只剩一个。
"""

import pytest

from voiceinput.config import Config
from voiceinput.delivery import FOCUS_RETURN_MS, Delivery


class FakeOutput:
    def __init__(self) -> None:
        self.pasted: list[tuple[str, bool]] = []
        self.copied: list[str] = []

    def paste_async(self, text, then_enter=False, on_done=None) -> None:
        self.pasted.append((text, then_enter))

    def copy(self, text) -> None:
        self.copied.append(text)

    @property
    def texts(self) -> list[str]:
        return [t for t, _ in self.pasted]


class Focus:
    """替身:记下"让出焦点"被叫了没有,并按需要谎报当时窗口在不在。"""

    def __init__(self, visible: bool) -> None:
        self._visible = visible
        self.yielded = False

    def __call__(self) -> bool:
        if not self._visible:
            return False
        self.yielded = True
        return True


@pytest.fixture
def make(qapp):
    def _make(visible: bool = True):
        focus = Focus(visible)
        d = Delivery(Config(), focus)
        d._output = FakeOutput()
        return d, focus, d._output
    return _make


def drain(ms: int = FOCUS_RETURN_MS + 200) -> None:
    """把挂起的 QTimer.singleShot 跑完。"""
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class TestResend:
    def test_让出焦点在先(self, make):
        d, focus, _ = make(visible=True)
        d.resend("你好")
        assert focus.yielded, "没让出焦点的话会粘进自己的搜索框"

    def test_让出焦点之后要等一会儿再粘(self, make):
        """系统把焦点还给上一个窗口需要时间,不能立刻粘。"""
        d, _, out = make(visible=True)
        d.resend("你好")
        assert out.texts == []          # 还没到时候
        drain()
        assert out.texts == ["你好"]

    def test_本来就没显示时不用等(self, make):
        d, focus, out = make(visible=False)
        d.resend("你好")
        drain(50)
        assert out.texts == ["你好"]
        assert not focus.yielded

    def test_粘完要给反馈(self, make):
        """窗口已经藏起来了,不给反馈用户不知道到底粘没粘。"""
        d, _, _ = make(visible=True)
        seen: list[str] = []
        d.pasted.connect(seen.append)
        d.resend("今天先把这段话整理一下")
        drain()
        assert seen == ["今天先把这段话整理一下"]

    def test_反馈交给别人决定要不要显示(self, make):
        """**"提示条关着就别显示"不是这里的判断。**

        那条规矩连同它的例外(失败提示不受关闭影响)一起归 Overlay 了 ——
        原来是五处调用点各自记着 `if show_overlay:`,迟早有一处漏掉。
        这里只保证:该说的话一定发出去。
        """
        d, _, out = make(visible=True)
        seen: list[str] = []
        d.pasted.connect(seen.append)
        d.resend("你好")
        drain()
        assert seen == ["你好"]
        assert out.texts == ["你好"]

    def test_等待时间要够用(self):
        """太短的话焦点还没还回去就粘了,等于没修。"""
        assert FOCUS_RETURN_MS >= 150


class TestSend:
    def test_刚说完的一句不用让焦点(self, make):
        """此刻前台是用户正在打字的那个窗口,藏自己反而是错的。"""
        d, focus, out = make(visible=True)
        d.send("你好")
        assert not focus.yielded
        assert out.texts == ["你好"]

    def test_粘贴并发送会带上回车(self, make):
        d, _, out = make()
        d.send("你好", then_enter=True)
        assert out.pasted == [("你好", True)]

    def test_没给期望窗口就照常贴(self, make):
        """`expected_window=None` = 调用方没给,或者这台机器判断不了
        前台窗口——两种都不该拦。"""
        d, _, out = make()
        d.send("你好", expected_window=None)
        assert out.texts == ["你好"]

    def test_目标窗口没变照常贴(self, make):
        d, _, out = make()
        d._foreground = lambda: 111
        d.send("你好", expected_window=111)
        assert out.texts == ["你好"]
        assert out.copied == []

    def test_目标窗口换了不硬贴(self, make):
        """说话 + 识别这段时间用户点去了别的窗口——贴错地方比不贴更糟,
        文字改放回剪贴板,不发到别的窗口去。"""
        d, _, out = make()
        d._foreground = lambda: 222   # 现在前台是别的窗口了
        d.send("你好", expected_window=111)
        assert out.texts == []
        assert out.copied == ["你好"]

    def test_目标窗口换了会发出提示信号(self, make):
        d, _, _ = make()
        d._foreground = lambda: 222
        seen: list[str] = []
        d.blocked.connect(seen.append)
        d.send("你好", expected_window=111)
        assert seen == ["你好"]


class TestApply:
    def test_配置变了三个字段都跟着走(self, make):
        """以前这三行写在 App 上(`_apply_output`),等于让 App 替
        输出这一摊记着它自己的配置。"""
        d, _, _ = make()
        cfg = Config()
        cfg.output.restore_clipboard = False
        cfg.output.paste_delay_ms = 123
        cfg.output.send_delay_ms = 45
        d.apply(cfg)
        assert d.output.restore_clipboard is False
        assert d.output.paste_delay_ms == 123
        assert d.output.send_delay_ms == 45
