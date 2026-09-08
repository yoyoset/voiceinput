"""文字输出:剪贴板 + Ctrl+V。

这是每次听写的**最后一步** —— 前面识别得再准,这里出问题也等于没用。
之前它一条测试都没有。

按键控制器是注入的假货:真的 `pynput.Controller` 会往当前焦点窗口发按键,
测试一跑就会把 Ctrl+V 打进跑测试的那个终端。
"""

import pytest

from pynput.keyboard import Key

from voiceinput.output import TextOutput


class FakeKeyboard:
    """记录按键顺序,不真的发出去。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def press(self, key) -> None:
        self.events.append(("press", key))

    def release(self, key) -> None:
        self.events.append(("release", key))

    @property
    def taps(self) -> list[tuple]:
        """把 press/release 折叠成"按了哪些组合"。"""
        out, pending = [], []
        for kind, key in self.events:
            if kind == "press":
                pending.append(key)
            elif pending:
                out.append(tuple(pending))
                pending = []
        return out


@pytest.fixture
def out(qapp):
    kb = FakeKeyboard()
    o = TextOutput(paste_delay_ms=1, send_delay_ms=1, keyboard=kb)
    o.kb = kb
    return o


def drain(ms: int = 400) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def clipboard():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance().clipboard()


class TestCopy:
    """目标窗口换了的时候用的那条路——只写剪贴板,不按键。"""

    def test_写剪贴板不按键(self, out):
        out.copy("你好世界")
        assert clipboard().text() == "你好世界"
        assert out.kb.events == []

    def test_空文本什么都不做(self, out):
        clipboard().setText("原来的东西")
        out.copy("")
        assert clipboard().text() == "原来的东西"


class TestPaste:
    def test_writes_text_to_clipboard(self, out):
        out.restore_clipboard = False
        out.paste("你好世界")
        assert clipboard().text() == "你好世界"

    def test_sends_ctrl_v(self, out):
        out.restore_clipboard = False
        out.paste("你好")
        assert out.kb.taps == [(Key.ctrl, "v")]

    def test_modifier_released_after(self, out):
        """Ctrl 必须松开,否则后续所有输入都变成 Ctrl+ 组合键。"""
        out.restore_clipboard = False
        out.paste("你好")
        assert ("release", Key.ctrl) in out.kb.events

    def test_release_order_is_reversed(self, out):
        """先按 Ctrl 后按 V,松开要反过来 —— 先松 Ctrl 会让 V 变成普通字符。"""
        out.restore_clipboard = False
        out.paste("你好")
        releases = [k for kind, k in out.kb.events if kind == "release"]
        assert releases == ["v", Key.ctrl]

    def test_empty_text_does_nothing(self, out):
        clipboard().setText("原有内容")
        out.paste("")
        assert out.kb.events == []
        assert clipboard().text() == "原有内容"

    def test_then_enter_sends_return(self, out):
        out.restore_clipboard = False
        out.paste("你好", then_enter=True)
        assert out.kb.taps == [(Key.ctrl, "v"), (Key.enter,)]

    def test_chinese_survives_clipboard(self, out):
        """keytyper 证明逐键模拟打不出中文,走剪贴板就是为了解决这个。"""
        out.restore_clipboard = False
        text = "把这个 function 改成 async,再跑一遍 pytest"
        out.paste(text)
        assert clipboard().text() == text


class TestClipboardRestore:
    def test_restores_previous_content(self, out):
        clipboard().setText("用户复制的东西")
        out.restore_clipboard = True
        out.paste("识别结果")
        assert clipboard().text() == "用户复制的东西"

    def test_can_be_disabled(self, out):
        clipboard().setText("用户复制的东西")
        out.restore_clipboard = False
        out.paste("识别结果")
        assert clipboard().text() == "识别结果"

    def test_restore_happens_after_paste(self, out):
        """还原必须在 Ctrl+V **之后**,否则粘出来的是旧内容。"""
        seen = []
        kb = out.kb

        original_press = kb.press

        def spy(key):
            if key == Key.ctrl:
                seen.append(clipboard().text())
            original_press(key)

        kb.press = spy
        clipboard().setText("旧的")
        out.restore_clipboard = True
        out.paste("新的")
        assert seen == ["新的"], "按 Ctrl+V 时剪贴板里必须已经是新内容"

    def test_empty_previous_clipboard(self, out):
        clipboard().clear()
        out.restore_clipboard = True
        out.paste("识别结果")
        assert clipboard().text() == ""


class TestPasteAsync:
    def test_completes_full_sequence(self, out):
        out.restore_clipboard = False
        out.paste_async("你好")
        drain()
        assert out.kb.taps == [(Key.ctrl, "v")]

    def test_does_not_send_keys_synchronously(self, out):
        """异步版不能在调用瞬间就发按键 —— 那样等于没异步。"""
        out.restore_clipboard = False
        out.paste_async("你好")
        assert out.kb.events == []

    def test_clipboard_written_synchronously(self, out):
        """剪贴板要立刻写:QClipboard 只能在主线程碰,拖到定时器里没必要。"""
        out.restore_clipboard = False
        out.paste_async("你好")
        assert clipboard().text() == "你好"

    def test_then_enter(self, out):
        out.restore_clipboard = False
        out.paste_async("你好", then_enter=True)
        drain()
        assert out.kb.taps == [(Key.ctrl, "v"), (Key.enter,)]

    def test_on_done_called(self, out):
        out.restore_clipboard = False
        done = []
        out.paste_async("你好", on_done=lambda: done.append(True))
        drain()
        assert done == [True]

    def test_on_done_called_even_for_empty_text(self, out):
        """空文本直接返回,但回调仍要触发,否则调用方会一直等。"""
        done = []
        out.paste_async("", on_done=lambda: done.append(True))
        assert done == [True]

    def test_restores_clipboard_after(self, out):
        clipboard().setText("用户的东西")
        out.restore_clipboard = True
        out.paste_async("识别结果")
        drain()
        assert clipboard().text() == "用户的东西"


class TestRestoreDelay:
    def test_never_shorter_than_floor(self, out):
        """还原等太短的话,目标应用还没读走新内容就被换回去了。"""
        out.paste_delay_ms = 10
        assert out._restore_delay_ms() >= 120

    def test_follows_paste_delay_when_larger(self, out):
        out.paste_delay_ms = 500
        assert out._restore_delay_ms() == 500


class TestRichClipboardIsPreserved:
    """**「粘贴后恢复原有剪贴板内容」原来只对纯文本成立。**

    实测过的三种破坏(都是静默的):

    | 剪贴板里原本是 | 旧实现还原之后 |
    |---|---|
    | 图片(截图) | 没了 —— `.text()` 是空串,还原等于 `setText("")` |
    | 复制的文件 | 退化成一个 `file:///...` 字符串,粘不出文件 |
    | 带格式的富文本 | 格式丢光 |

    而 output.py 顶部写着"用户复制在剪贴板里的东西不能被默默吞掉"。
    """

    def mime_with(self, **kw):
        from PySide6.QtCore import QMimeData

        m = QMimeData()
        for key, value in kw.items():
            getattr(m, f"set{key.capitalize()}")(value)
        return m

    def test_image_survives(self, out):
        from PySide6.QtGui import QColor, QImage

        img = QImage(4, 4, QImage.Format.Format_RGB32)
        img.fill(QColor("red"))
        clipboard().setImage(img)

        out.restore_clipboard = True
        out.paste("识别结果")

        back = clipboard().image()
        assert not back.isNull(), "用户复制的图片被吞掉了"
        assert (back.width(), back.height()) == (4, 4)
        assert back.pixelColor(0, 0).name() == "#ff0000"

    def test_files_survive(self, out):
        from PySide6.QtCore import QUrl

        clipboard().setMimeData(self.mime_with(urls=[QUrl.fromLocalFile("C:/x.txt")]))
        out.restore_clipboard = True
        out.paste("识别结果")

        data = clipboard().mimeData()
        assert data.hasUrls(), "复制的文件退化成了一个 file:// 字符串"
        assert data.urls()[0].toLocalFile().endswith("x.txt")

    def test_html_survives(self, out):
        clipboard().setMimeData(self.mime_with(html="<b>粗体</b>", text="粗体"))
        out.restore_clipboard = True
        out.paste("识别结果")

        data = clipboard().mimeData()
        assert data.hasHtml(), "富文本的格式丢了"
        assert "粗体" in data.html()

    def test_plain_text_still_works(self, out):
        """原来唯一能用的那种情况不能改坏。"""
        clipboard().setText("用户复制的文字")
        out.restore_clipboard = True
        out.paste("识别结果")
        assert clipboard().text() == "用户复制的文字"

    def test_image_format_cannot_be_copied_byte_wise(self, out):
        """**钉住那个让人踩坑的事实。**

        到处都查得到的"遍历 formats() 逐个 setData"深拷贝写法,对图片
        会静默失败 —— `data("application/x-qt-image")` 返回 0 字节,
        因为图片在剪贴板里是 QVariant 而不是原始字节。
        """
        from PySide6.QtGui import QColor, QImage

        img = QImage(4, 4, QImage.Format.Format_RGB32)
        img.fill(QColor("red"))
        clipboard().setImage(img)
        data = clipboard().mimeData()
        assert data.hasImage()
        assert data.data("application/x-qt-image").size() == 0

    def test_oversized_clipboard_is_skipped_not_copied(self, out, monkeypatch):
        """剪贴板里是个几十兆的东西时放弃还原,别为了 200 毫秒占那么多内存。"""
        import voiceinput.output as output_mod

        monkeypatch.setattr(output_mod, "MAX_RESTORE_BYTES", 8)
        clipboard().setText("这段文字超过八个字节了")
        assert out._read_clipboard() is None
