"""识别历史现在记不记、记多少。

拆出来的判据和 `hotkey_host` / `microphone` 是同一条:那个 History 对象
(可能是 None)的开关归它自己管,"配置变没变"也归它自己判断 ——
以前这两件事分别写在 App 的字段和 App 的配置分发里。

一条不能改的行为:**关掉记录不删已有记录**。用户想的是"以后别记了",
不是"把过去也抹掉"。真要清空,界面上有单独的按钮,那是个需要确认的
破坏性操作。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from .config import Config
from .history import History

log = logging.getLogger("voiceinput")


class HistoryHost(QObject):
    """历史数据库的开关。"""

    changed = Signal(object)
    """History | None —— 换了对象(或者关掉了),界面得跟着换。"""

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._enabled = cfg.history.enabled
        self._max_entries = cfg.history.max_entries
        self._db = History(max_entries=self._max_entries) if self._enabled else None

    @property
    def current(self) -> History | None:
        """当前的历史库。关掉记录时是 None —— 调用方必须处理这种情况。"""
        return self._db

    def apply(self, cfg: Config) -> None:
        """按配置开关历史、改上限。**和上次一样就什么都不做。**"""
        if (cfg.history.enabled == self._enabled
                and cfg.history.max_entries == self._max_entries):
            return
        self._enabled = cfg.history.enabled
        self._max_entries = cfg.history.max_entries

        if not self._enabled:
            self.close()
            log.info("历史记录已关闭")
        elif self._db is None:
            self._db = History(max_entries=self._max_entries)
            log.info("历史记录已开启")
        else:
            # 上限调小了要立刻生效,不能等到下次写入才裁剪
            self._db.set_max_entries(self._max_entries)
        self.changed.emit(self._db)

    def add(self, *args, **kwargs) -> None:
        """写一条。关着就什么都不做。

        **写历史失败不该影响这次听写** —— 文字已经粘出去了,
        记不下来是个次要问题,不能因此弹错误盖掉成功的结果。
        """
        if self._db is None:
            return
        try:
            self._db.add(*args, **kwargs)
        except Exception as e:
            log.warning("写历史失败: %s", e)

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
