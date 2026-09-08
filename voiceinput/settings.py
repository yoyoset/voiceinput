"""当前生效的配置,以及它变了之后谁要跟着动。

拆出来的判据是**谁在改这个状态**:那份 Config,和它的落盘。以前是 App 上的
`self.cfg` 加一个几十行的分发函数 —— 而"谁要跟着动"是**一串语句**,
读的人得从头看到尾才知道有哪些子系统参与。

现在它是一份**名单**(`follow()`),和 `Theme.watch()` 同一个模式。
新加一个子系统时忘了登记,表现仍然是"改了设置对它没生效" ——
但名单在一处、看得见,而不是散在一串 if 里。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject

from . import config as config_mod
from .config import Config

log = logging.getLogger("voiceinput")

Applier = Callable[[Config], None]


class Settings(QObject):
    """配置的唯一来源。"""

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._followers: list[Applier] = []

    @property
    def current(self) -> Config:
        return self._cfg

    def follow(self, *appliers: Applier) -> None:
        """登记"配置变了要通知我"。

        收的是回调而不是对象:有的子系统方法叫 `apply`,有的要现场拼一句
        (比如把 `cfg.ui.overlay_corner` 递给悬浮条)—— 统一成回调,
        名单里每一行都读得懂在干什么。
        """
        self._followers.extend(appliers)

    def update(self, cfg: Config) -> None:
        """换成新配置:**先落盘,再通知**。

        顺序不能反。通知过程中任何一个 follower 抛异常都会中断后面的,
        而那时配置已经在内存里生效了 —— 不先存盘的话,用户重启一次
        改动就没了,而界面上明明显示改过。
        """
        self._cfg = cfg
        self.save()
        for apply in self._followers:
            apply(cfg)

    def save(self) -> None:
        """只落盘,不通知。

        拖动悬浮麦克风走这条:位置是直接改在 Config 上的,没有"新配置"
        这回事,也不需要惊动任何子系统。
        """
        try:
            config_mod.save(self._cfg)
        except OSError as e:
            # 存不下来不该拦住程序 —— 这次改动在内存里仍然生效
            log.error("保存配置失败: %s", e)
