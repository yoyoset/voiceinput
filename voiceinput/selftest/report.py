"""自检的输出与结论。

拆出来的判据是**谁在改这些状态**:已经写了哪几行、结论是不是还成立 ——
以前这两样是 `run()` 里的闭包变量 `lines` 和 `ok`,十几个地方各自读写。

而 `ok = False` 必须紧跟在每一句 `[失败]` 后面,靠人记得写。
漏一次的后果是:界面上报了失败,退出码却是 0 —— 自检说"存在失败项"
和它返回给调用方的东西不一致。现在 `failed()` 把两件事绑成一个动作,
想漏也漏不掉。
"""

from __future__ import annotations

import sys
from pathlib import Path


def safe_print(msg: str) -> None:
    """打一行,**编码问题不许让这一行消失**。

    中文 Windows 的控制台是 GBK,而 `✓`(U+2713)这类字符 GBK 编不出来 ——
    `print` 会抛 UnicodeEncodeError。原来这里是 `except Exception: pass`,
    于是整行从控制台消失,而报告文件(UTF-8)里却有。

    实测踩过:自检里两条热键结论就是这样凭空不见的,看起来像"那段代码
    根本没跑",查了半天才发现是编码。**自检本身出现静默失败,
    比它要检查的那些问题更坏。**
    """
    try:
        print(msg, flush=True)
        return
    except UnicodeEncodeError:
        pass
    except Exception:
        return          # frozen + console=False 时没有可用的 stdout
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(msg.encode(enc, "replace").decode(enc, "replace"), flush=True)
    except Exception:
        pass


class Report:
    """自检写出来的东西,以及"到目前为止是否全过"。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lines: list[str] = []
        self._ok = True

    @property
    def ok(self) -> bool:
        return self._ok

    @property
    def text(self) -> str:
        return "\n".join(self._lines) + "\n"

    # ---- 写 ----

    def line(self, msg: str) -> None:
        """原样写一行。

        **每写一行就落一次盘,不能等跑完再写**:自检的价值恰恰在于定位
        "卡在哪一步",而卡住的时候正是写不到最后那一步的时候。
        第一版就是只在末尾写文件,结果 exe 卡死后什么线索都没留下。
        """
        self._lines.append(msg)
        try:
            self._path.write_text(self.text, encoding="utf-8")
        except OSError:
            pass
        safe_print(msg)

    def passed(self, msg: str) -> None:
        self.line(f"[通过] {msg}")

    def failed(self, msg: str) -> None:
        """报一个失败,**并把结论置为不通过** —— 这两件事绑在一起。"""
        self._ok = False
        self.line(f"[失败] {msg}")

    def noted(self, msg: str) -> None:
        """值得说,但不算这个程序的问题(比如热键被别的软件占了)。"""
        self.line(f"[注意] {msg}")

    def verdict(self, ok: bool, msg: str) -> None:
        """按条件报通过或失败。"""
        (self.passed if ok else self.failed)(msg)

    def detail(self, msg: str) -> None:
        """上一行的补充,缩进显示。不单独构成结论。"""
        self.line(f"        {msg}")
