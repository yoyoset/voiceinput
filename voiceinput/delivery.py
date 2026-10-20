"""把文字送到光标处。

拆出来的判据是**谁在改这个状态**:那个 TextOutput 实例,以及它那三个
延迟参数。以前 TextOutput 归 App 拿着,而"配置变了要把三个字段推给它"
是 App 上一个叫 `_apply_output` 的方法 —— 等于让 App 替输出这一摊
记着它自己的配置。现在 `apply()` 自己认领自己那几项。

**送出去有两条路,区别只在"谁抢着焦点"**:

- `send()`:说完一句话之后。此刻前台窗口是用户正在打字的那个,直接粘。
- `resend()`:从历史里点「重新粘贴」。此刻前台窗口是 VoiceInput 自己,
  直接粘会粘进它自己的搜索框 —— 必须先把自己藏起来,等系统把焦点
  还给上一个窗口,再粘。

第二条路以前和第一条一起躺在 App 里,而它俩看着很像 —— 像到很容易
在改其中一条时忘了另一条不一样。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .config import Config
from .foreground import foreground_window
from .output import TextOutput

log = logging.getLogger("voiceinput")

# 藏起自己到发送 Ctrl+V 之间的等待。
# 要留够时间让系统把焦点还给用户上一个使用的窗口。
FOCUS_RETURN_MS = 300


class Delivery(QObject):
    """文字的送出。"""

    pasted = Signal(str)
    """已经送出去了。窗口这时候是藏着的,不给反馈用户不知道粘没粘。"""

    blocked = Signal(str)
    """该贴的时候目标窗口已经不是当初那个了,没有硬贴——文字留在剪贴板,
    交给外面(App)决定怎么提示用户。"""

    def __init__(self, cfg: Config, yield_focus: Callable[[], bool],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        # `yield_focus` 收的是回调而不是窗口对象:这里不该认识主窗口,
        # 它只需要知道"让出焦点"这件事做没做。
        self._yield_focus = yield_focus
        # 同样收回调而不是直接调用全局函数——测试要能喂假的前台窗口,
        # 不然没法在不真的切窗口的情况下验证"换了就不硬贴"这条分支。
        self._foreground = foreground_window
        self._output = TextOutput(
            restore_clipboard=cfg.output.restore_clipboard,
            paste_delay_ms=cfg.output.paste_delay_ms,
            send_delay_ms=cfg.output.send_delay_ms,
        )

    @property
    def output(self) -> TextOutput:
        """底层的输出器。自检要看它的参数。"""
        return self._output

    def apply(self, cfg: Config) -> None:
        """配置变了。三个字段都是纯赋值,没有"变了才做"的必要。"""
        self._output.restore_clipboard = cfg.output.restore_clipboard
        self._output.paste_delay_ms = cfg.output.paste_delay_ms
        self._output.send_delay_ms = cfg.output.send_delay_ms

    def send(self, text: str, then_enter: bool = False,
              expected_window: int | None = None) -> None:
        """刚说完的一句话。前台窗口是用户正在打字的那个,直接粘。

        `expected_window` 是按下热键那一刻的前台窗口。说话 + 识别这段时间
        用户可能点去了别的窗口——这时前台已经不是当初那个了,**不硬贴过去**
        (贴错地方比不贴更糟,而且贴错了还不容易发现),只把文字放回剪贴板,
        交给外面提示"自己贴一下"。`None` 表示调用方没给,或者这台机器上
        判断不了前台窗口(见 `foreground.py`)——两种情况都不拦,照常贴。
        """
        # 两条分支都记日志。2026-09-15 连丢两句时日志里只有"识别成功",
        # 分不出是贴了但没落进输入框、还是窗口变了没敢贴 —— 只能猜。
        current = self._foreground()
        if expected_window is not None and current != expected_window:
            log.warning("目标窗口已切换(按下时 %s,现在 %s),没有粘贴,已放进剪贴板",
                        expected_window, current)
            self._output.copy(text)
            self.blocked.emit(text)
            return
        log.info("已发送粘贴 窗口=%s 回车=%s", current, then_enter)
        self._output.paste_async(text, then_enter=then_enter)

    def resend(self, text: str) -> None:
        """历史里的一条,重新粘出去。

        **必须先把自己藏起来。** 用户是点主窗口里的按钮触发的,此刻前台
        窗口就是 VoiceInput 自己 —— 直接发 Ctrl+V 会粘进它自己的历史搜索框。
        (原来的提示文案写着"先切到目标窗口再操作",但切走了就点不到按钮,
        自相矛盾,那个功能按文案描述的方式根本用不了。)
        """
        delay = FOCUS_RETURN_MS if self._yield_focus() else 0

        def do_paste() -> None:
            self._output.paste_async(text)
            self.pasted.emit(text)

        QTimer.singleShot(delay, do_paste)
