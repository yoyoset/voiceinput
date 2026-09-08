"""当前用的是哪套配色。

拆出来的判据是**谁在改这个状态**:那个 Palette,和"换了配色之后谁需要
被通知"。以前 palette 是 App 上的一个字段,而通知名单只存在于配置分发里
那个 `if cfg.ui.theme != old.ui.theme` 的分支内 ——
新加一个带配色的控件,得记得回去那个 if 里补一行。
漏了的表现是**换主题之后有一个控件还是旧颜色**,而且不报错。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from .theme import Palette, apply_theme

Listener = Callable[[Palette], None]


class Theme(QObject):
    """配色的唯一来源,以及它的订阅者。"""

    def __init__(self, qapp: QApplication, cfg, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._qapp = qapp
        self._name = cfg.ui.theme
        self._palette = apply_theme(qapp, self._name)
        self._listeners: list[Listener] = []

    @property
    def palette(self) -> Palette:
        return self._palette

    def watch(self, *listeners: Listener) -> None:
        """登记"换配色时要通知我"。

        收的是回调而不是控件:主窗口的方法叫 `apply_palette`,悬浮条叫
        `set_palette` —— 靠 getattr 猜名字只会在某天悄悄漏掉一个。
        """
        self._listeners.extend(listeners)

    def apply(self, cfg) -> None:
        """配置变了。**没换主题就什么都不做** —— 重算样式表不便宜,
        而配置保存是防抖后批量发的。"""
        if cfg.ui.theme == self._name:
            return
        self._name = cfg.ui.theme
        self._palette = apply_theme(self._qapp, self._name)
        for notify in self._listeners:
            notify(self._palette)
