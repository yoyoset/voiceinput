"""把文字送到当前光标处。

**为什么走剪贴板而不是模拟按键**:同目录的 keytyper 项目(Rust + enigo)已经证明
逐字符 VK 模拟打不出中文——它的 `ascii_vk()` 对非 ASCII 返回 None,UI 里还得把
中文标红提示"输入时跳过"。这个坑不用再踩第二遍。

剪贴板必须**先备份、粘贴后恢复**:用户复制在剪贴板里的东西不能被默默吞掉。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from pynput.keyboard import Controller, Key

log = logging.getLogger("voiceinput")

# 还原剪贴板时愿意暂存的上限。4K 截图的未压缩位图能到几十兆,
# 为了 200 毫秒的还原去占那么多内存不划算。
MAX_RESTORE_BYTES = 32 * 1024 * 1024

# Qt 给图片用的内部格式。它的 data() 是空的,得走 imageData()。
_QT_IMAGE_FORMAT = "application/x-qt-image"


class OutputError(RuntimeError):
    pass


class TextOutput:
    """剪贴板 + Ctrl+V。

    剪贴板走 Qt 的 QClipboard:Qt 本来就在依赖里,而且它对 Unicode 的处理
    比自己调 win32 API 省事。
    """

    def __init__(self, restore_clipboard: bool = True, paste_delay_ms: int = 80,
                 send_delay_ms: int = 60, keyboard=None) -> None:
        self.restore_clipboard = restore_clipboard
        self.paste_delay_ms = paste_delay_ms
        self.send_delay_ms = send_delay_ms
        # keyboard 可注入**纯粹是为了能测**:真的 Controller 会往当前焦点窗口
        # 发按键,测试里一跑就会把 Ctrl+V 打进跑测试的那个终端。
        self._keyboard = keyboard if keyboard is not None else Controller()

    # ---- 剪贴板 ----

    @staticmethod
    def _clipboard():
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            raise OutputError("QApplication 尚未创建,无法访问剪贴板")
        return app.clipboard()

    def _read_clipboard(self) -> tuple | None:
        """把剪贴板现有内容拷一份。返回 `(格式表, 图片)`,拷不了返回 None。

        **原来这里只存 `.text()`,实测会毁掉用户的东西:**

        | 剪贴板里原本是 | 还原之后 |
        |---|---|
        | 图片(截图) | 没了 —— `.text()` 是空串,还原等于 `setText("")` |
        | 复制的文件 | 退化成一个 `file:///...` 字符串,粘不出文件 |
        | 带格式的富文本 | 格式丢光 |

        三种都是**静默**的:用户复制了张图,说一句话,图就没了,
        没有任何提示。而这个模块顶部写着"不能被默默吞掉"。

        两个必须绕开的坑:

        1. **图片不能按格式拷。** 到处都查得到的"遍历 `formats()` 逐个
           `setData`"那个写法,对图片会**静默失败** —— 实测
           `data("application/x-qt-image")` 返回 **0 字节**,因为图片在
           剪贴板里是个 QVariant 而不是原始字节。得走 `imageData()`。
        2. **不能存 QMimeData 对象本身。** `mimeData()` 返回的是剪贴板自己
           持有的东西,我们一写新内容它就失效;而 `setMimeData()` 会**接管
           所有权**,存着一个两边都认为自己该释放的对象会在退出时段错误。
           所以这里只存纯数据,`_restore` 现造一个交出去。
        """
        try:
            src = self._clipboard().mimeData()
            if src is None:
                # 剪贴板本来就是空的。**这不是失败** —— 返回空快照,
                # 还原时把它清回空。返回 None 会被当成"别还原",
                # 于是我们的识别结果就留在剪贴板里不走了。
                return {}, None
            image = src.imageData() if src.hasImage() else None
            blobs: dict[str, bytes] = {}
            total = 0
            for fmt in src.formats():
                if fmt == _QT_IMAGE_FORMAT:
                    continue          # 上面已经按图片取过了
                data = bytes(src.data(fmt))
                total += len(data)
                if total > MAX_RESTORE_BYTES:
                    # 剪贴板里是个巨大的东西。与其占着几十兆等 200 毫秒,
                    # 不如放弃还原并说一声。
                    log.warning("剪贴板内容过大(>%d MB),这次不还原",
                                MAX_RESTORE_BYTES // 1024 // 1024)
                    return None
                blobs[fmt] = data
            return blobs, image
        except Exception as e:
            log.warning("备份剪贴板失败,这次不还原: %s", e)
            return None

    def _write_clipboard(self, text: str) -> None:
        try:
            self._clipboard().setText(text)
        except Exception as e:
            raise OutputError(f"写剪贴板失败: {e}") from e

    def copy(self, text: str) -> None:
        """只写剪贴板,不粘贴。

        目标窗口已经换了的时候用这条——硬贴只会贴错地方,比不贴更糟。
        不备份/不还原原来的剪贴板:识别结果本身就是要交给用户的东西,
        它得一直留在剪贴板里等着被贴,不能过一会儿被悄悄换回旧内容。
        """
        if not text:
            return
        self._write_clipboard(text)

    # ---- 发送 ----

    def _tap(self, *keys: Key | str) -> None:
        """按下一组键再反序松开。"""
        pressed = []
        try:
            for k in keys:
                self._keyboard.press(k)
                pressed.append(k)
        finally:
            for k in reversed(pressed):
                try:
                    self._keyboard.release(k)
                except Exception:
                    pass

    def paste(self, text: str, then_enter: bool = False) -> None:
        """阻塞版粘贴。**只在测试里用。**

        两个理由,第二个是实测出来的:

        1. 这里的 sleep 跑在主线程会把界面冻住两百来毫秒。
        2. **在真实 Windows 上它还原不了富内容。** sleep 期间事件循环是死的,
           而 Windows 的剪贴板要靠窗口消息才能完成交接 —— 实测图片和纯文本
           都还原失败,而同样的内容走 `paste_async` 全部正常。
           (offscreen 平台的剪贴板是进程内的,不经过这套机制,所以
           单元测试里看不出这个差别。)
        """
        if not text:
            return
        previous = self._read_clipboard() if self.restore_clipboard else None
        self._write_clipboard(text)

        # 给目标应用留出读到新剪贴板内容的时间。太短的话某些应用会粘到旧内容。
        time.sleep(self.paste_delay_ms / 1000)
        self._tap(Key.ctrl, "v")

        if then_enter:
            time.sleep(self.send_delay_ms / 1000)
            self._tap(Key.enter)

        if previous is not None:
            time.sleep(self._restore_delay_ms() / 1000)
            self._restore(previous)

    def paste_async(self, text: str, then_enter: bool = False,
                    on_done: Callable[[], None] | None = None) -> None:
        """用 QTimer 串起整个流程,不阻塞主线程。

        剪贴板必须在主线程访问(QClipboard 的要求),而各步之间的等待又不能用
        sleep,所以拆成几个定时回调。
        """
        if not text:
            if on_done:
                on_done()
            return

        from PySide6.QtCore import QTimer

        previous = self._read_clipboard() if self.restore_clipboard else None
        self._write_clipboard(text)

        elapsed = self.paste_delay_ms

        def do_paste() -> None:
            self._tap(Key.ctrl, "v")

        QTimer.singleShot(elapsed, do_paste)

        if then_enter:
            elapsed += self.send_delay_ms
            QTimer.singleShot(elapsed, lambda: self._tap(Key.enter))

        if previous is not None:
            elapsed += self._restore_delay_ms()
            QTimer.singleShot(elapsed, lambda: self._restore(previous))

        if on_done:
            QTimer.singleShot(elapsed + 20, on_done)

    def _restore_delay_ms(self) -> int:
        """还原剪贴板前的等待。

        还原得太早的话,目标应用可能还没把新内容读走,结果粘出来的是旧东西。
        120ms 是个保守下限。
        """
        return max(self.paste_delay_ms, 120)

    def _restore(self, previous: tuple) -> None:
        """把之前那份内容放回去。**在这里现造 QMimeData 再交出去** ——
        `setMimeData` 会接管所有权,不能给它一个我们还留着引用的对象。

        还原失败**不该让整次输入算作失败** —— 文字已经粘出去了,
        用户要的事情已经成了。
        """
        from PySide6.QtCore import QByteArray, QMimeData

        blobs, image = previous
        try:
            mime = QMimeData()
            for fmt, data in blobs.items():
                mime.setData(fmt, QByteArray(data))
            if image is not None:
                mime.setImageData(image)
            self._clipboard().setMimeData(mime)
        except Exception as e:
            log.warning("还原剪贴板失败: %s", e)
