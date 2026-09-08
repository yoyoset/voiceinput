"""悬浮麦克风摆在哪、显不显示。

拆出来的判据是**谁在改这个状态**:配置里那对坐标。它有个别处没有的特点 ——
**它是被用户用鼠标拖出来的**,不经过设置页,所以也就不走设置页那套
防抖保存。拖完必须当场落盘,否则程序一关位置就没了。

以前这件事分两半住在 App 里:`_apply_badge()` 负责摆放,
`_on_badge_moved()` 负责记住。而"摆放"那半在启动和配置变更时曾经
各写过一遍,逻辑已经不一样了(见下面 apply 的注释)。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject

from ..config import Config

log = logging.getLogger("voiceinput")


class BadgePlacement(QObject):
    """把配置里的位置与显隐落到那个悬浮按钮上。"""

    def __init__(self, badge, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._badge = badge
        self._settings = settings
        badge.moved.connect(self._remember)

    def apply(self, cfg: Config) -> None:
        """摆好、该显示就显示。启动和配置变更走的是同一条路。

        原来两处各写一遍,而且**逻辑已经不一样了**:启动那边是
        "存过位置就用存的",配置变更那边是"坐标是负的就挪回默认" ——
        两者当时恰好等价纯属巧合,再改一次就会分叉。
        """
        if cfg.ui.mic_badge_x >= 0 and cfg.ui.mic_badge_y >= 0:
            self._badge.move_to(cfg.ui.mic_badge_x, cfg.ui.mic_badge_y)
        else:
            self._badge.move_to_default()   # -1 = 设置页点了「挪回默认位置」
        self._badge.setVisible(cfg.ui.show_mic_badge)

    def _remember(self, x: int, y: int) -> None:
        """用户拖完了。**当场落盘**,不等设置页那套防抖 ——
        拖动根本不经过设置页,没人会替它触发保存。"""
        cfg = self._settings.current
        cfg.ui.mic_badge_x = x
        cfg.ui.mic_badge_y = y
        self._settings.save()
