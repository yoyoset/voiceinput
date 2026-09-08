"""现在注册着哪些热键。

拆出来的判据是**谁在改这个状态**:那个 HotkeyManager 实例、和它当前绑的组合。
以前是 App 上的 `self.hotkeys`,由启动、配置变更、退出三处各自读写,
而"配置里的热键有没有变"这个判断还写在 App 的配置分发里 ——
等于让 App 替热键这一摊记着它自己的旧值。

现在 `apply()` 自己比对自己的旧值:没变就什么都不做。

**回调跑在 pynput 自己的监听线程上。** 里面绝不能做耗时的事,否则整个
键盘事件队列被堵住,表现为系统级卡键。所以这里只把它们翻成 Qt 信号,
由队列连接甩到主线程。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from .config import Config
from .hotkey import ACTION_LABELS, HotkeyError, HotkeyManager, describe, labelled

log = logging.getLogger("voiceinput")


class HotkeyHost(QObject):
    """全局热键的注册与注销。"""

    startRequested = Signal(str)     # action
    stopRequested = Signal(str)
    upgradeRequested = Signal(str)
    """按下时先命中了较短的组合,补按修饰键后升级成更具体的那个。"""

    registerFailed = Signal(str)

    conflictDetected = Signal(str)
    """注册成功了,但有组合被别的程序占着。参数是被占的动作名。

    **这不是错误,是必须说出来的事实** —— 按下去两个程序会一起动,
    而且不会有任何报错。
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager: HotkeyManager | None = None
        self._bindings: dict[str, str] = {}
        self._mode = ""
        self._taken: set[str] = set()

    # ---- 注册 ----

    def apply(self, cfg: Config) -> None:
        """按配置(重新)注册。**和上次一样就什么都不做。**

        由这里自己比对,而不是让调用方替我们记着旧值 —— 那样每加一个
        热键相关的配置项,调用方那边的 if 就得跟着改一次。
        """
        bindings = {
            "paste": cfg.hotkey.paste,
            "paste_and_send": cfg.hotkey.paste_and_send,
        }
        if self._manager is not None \
                and bindings == self._bindings and cfg.hotkey.mode == self._mode:
            return

        self.stop()
        try:
            self._manager = HotkeyManager(
                bindings,
                mode=cfg.hotkey.mode,
                on_start=self.startRequested.emit,
                on_stop=self.stopRequested.emit,
                on_upgrade=self.upgradeRequested.emit,
                on_error=lambda msg: log.error("%s", msg),
            )
            self._manager.start()
        except HotkeyError as e:
            self._manager = None
            log.error("热键注册失败: %s", e)
            self.registerFailed.emit(str(e))
            return

        self._bindings, self._mode = bindings, cfg.hotkey.mode
        log.info("热键已注册: %s", bindings)
        self._check_conflicts(bindings)

    def _check_conflicts(self, bindings: dict[str, str]) -> None:
        """注册成功不等于按下去只有我们响应。

        pynput 用的是底层键盘钩子,**不吞按键** —— 别的程序占着同一个组合时,
        注册照样成功,按下去两边同时触发。这不会报任何错。

        **所以必须主动说出来。** 只写日志等于没说:用户按下去发现两个程序
        一起动,不会想到去翻日志,更不会想到去设置页点"检查占用"。

        结论的措辞来自 `conflict.Verdict` —— 设置页、向导、自检显示的是同一份。
        """
        self._taken = set()
        try:
            from . import conflict
        except ImportError:      # pragma: no cover - 不该发生,但不值得因此崩掉
            return
        # 用给用户看的名字 —— 日志里出现内部键名 `paste`,
        # 和设置页上的说法对不上
        for key, verdict in zip(bindings, conflict.report(labelled(bindings))):
            if verdict.taken is True:
                self._taken.add(key)
                log.warning("%s(按下去会两边同时触发)", verdict.describe())
        if self._taken:
            self.conflictDetected.emit(
                "、".join(ACTION_LABELS.get(k, k) for k in sorted(self._taken)))

    def stop(self) -> None:
        if self._manager is not None:
            self._manager.stop()
            self._manager = None

    # ---- 说给用户听 ----

    def summary(self) -> str:
        """状态栏上那句"按哪个键"。改了热键之后总得有处可查。

        被别的程序占着的那个会带一个记号 —— 状态栏说"按 X"而按下去
        两个程序一起动,比不说更坏。
        """
        if not self._bindings:
            return ""
        return " · ".join(
            f"{describe(self._bindings[key])}{tail}"
            f"{'(被占用)' if key in self._taken else ''}"
            for key, tail in (("paste", " 说话粘贴"), ("paste_and_send", " 粘贴并发送")))
