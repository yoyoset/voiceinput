"""按下去有反应吗。

**键盘钩子是整个程序的开关。** 打包之后 pynput 装不上钩子的话,
按热键什么都不会发生 —— 而模型、界面、音频全都会显示"通过"。
"""

from __future__ import annotations

from ..config import Config
from .report import Report


def check_hook(report: Report) -> None:
    """装一次全局键盘钩子,立刻卸掉。

    监听器不吞按键,不会影响正在用电脑的人。
    """
    try:
        from pynput import keyboard

        listener = keyboard.Listener(on_press=lambda k: None, on_release=lambda k: None)
        listener.daemon = True
        listener.start()
        listener.wait()          # 等钩子真正装好,不然测的是"没报错"而已
        running = listener.running
        listener.stop()
        report.verdict(running, "全局热键钩子可用" if running
                       else "全局热键钩子装不上 —— 按热键将完全没有反应")
    except Exception as e:
        report.failed(f"全局热键: {e}")


def check_cancel_key(report: Report) -> None:
    """录音时按 Esc 取消,靠的是不是同一个 pynput 全局监听器。

    **证伪轮挖出来的一条从没验证过的假设。** `check_hook` 验证的是一个
    临时装的监听器,不是 `CancelKey` 这个类本身;而 `CancelKey.start()`
    和上面那个不一样——它不调用 `listener.wait()`,只管 `start()` 就
    返回。如果钩子在装的过程中失败、或者装上了但 `running` 迟迟不是
    True,`CancelKey.start()` 完全不会知道,用户按 Esc 会毫无反应,
    而程序不会报任何错——这正是这个项目最想排除的那类失败。

    这里替它多做 `check_hook` 做过的那一步(`wait()` 再看 `running`),
    才是真的验证过,不是"构造函数没抛异常"而已。
    """
    try:
        from ..cancel_key import CancelKey

        key = CancelKey()
        key.start()
        listener = key._listener
        if listener is not None:
            listener.wait()
        running = listener is not None and listener.running
        key.stop()
        report.verdict(running, "Esc 取消监听可用" if running
                       else "Esc 取消监听装不上 —— 按 Esc 将完全没有反应")
    except Exception as e:
        report.failed(f"Esc 取消监听: {e}")


def check_conflicts(report: Report, cfg: Config) -> None:
    """配置里写的热键,现在有没有被别的程序占着。

    **这不算失败** —— 用户装了什么不是程序的错。但必须说出来:
    撞了的表现是"按热键两边同时反应",而不是任何报错。
    """
    try:
        from .. import conflict

        # 措辞来自 conflict.Verdict、名字来自 hotkey.ACTION_LABELS ——
        # 界面上显示的是同一份
        from ..hotkey import labelled

        for verdict in conflict.report(labelled({
                "paste": cfg.hotkey.paste,
                "paste_and_send": cfg.hotkey.paste_and_send})):
            line = f"热键{verdict.describe()}"
            report.passed(line) if verdict.ok else report.noted(line)
    except Exception as e:
        report.noted(f"热键占用探测跑不了: {e}")
