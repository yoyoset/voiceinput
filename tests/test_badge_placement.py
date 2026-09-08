"""悬浮麦克风的位置与显隐。

这份状态有个别处没有的特点:**它是被用户用鼠标拖出来的**,不经过设置页,
所以也不走设置页那套防抖保存。拖完必须当场落盘,否则程序一关位置就没了。
"""

import pytest

from voiceinput.config import Config
from voiceinput.ui.badge_placement import BadgePlacement


class FakeBadge:
    """替身 —— 真的悬浮窗会在屏幕上冒出来。"""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class _Sig(QObject):
            moved = Signal(int, int)

        self._sig = _Sig()
        self.moved = self._sig.moved
        self.moved_to: list = []
        self.defaulted = 0
        self.visible: list = []

    def move_to(self, x, y):
        self.moved_to.append((x, y))

    def move_to_default(self):
        self.defaulted += 1

    def setVisible(self, on):  # noqa: N802 - 学 Qt 的名字
        self.visible.append(on)


class FakeSettings:
    def __init__(self, cfg):
        self.current = cfg
        self.saves = 0

    def save(self):
        self.saves += 1


@pytest.fixture
def rig(qapp):
    cfg = Config()
    badge = FakeBadge()
    settings = FakeSettings(cfg)
    return badge, settings, cfg, BadgePlacement(badge, settings)


class TestApply:
    def test_stored_position_is_used(self, rig):
        badge, _, cfg, placement = rig
        cfg.ui.mic_badge_x, cfg.ui.mic_badge_y = 300, 400
        placement.apply(cfg)
        assert badge.moved_to == [(300, 400)]
        assert badge.defaulted == 0

    def test_negative_means_go_home(self, rig):
        """-1 是「挪回默认位置」按钮留下的哨兵值 ——
        换了显示器之后找不着它了,那是唯一不靠鼠标找回来的办法。"""
        badge, _, cfg, placement = rig
        cfg.ui.mic_badge_x, cfg.ui.mic_badge_y = -1, -1
        placement.apply(cfg)
        assert badge.defaulted == 1
        assert badge.moved_to == []

    def test_one_negative_coordinate_is_enough(self, rig):
        """只有一半坐标有效也当没有 —— 半个位置摆不出来。"""
        badge, _, cfg, placement = rig
        cfg.ui.mic_badge_x, cfg.ui.mic_badge_y = 300, -1
        placement.apply(cfg)
        assert badge.defaulted == 1

    def test_visibility_follows_config(self, rig):
        badge, _, cfg, placement = rig
        cfg.ui.show_mic_badge = False
        placement.apply(cfg)
        assert badge.visible == [False]


class TestRemember:
    def test_dragging_saves_immediately(self, rig):
        """**拖动不经过设置页,没人会替它触发保存。**"""
        badge, settings, cfg, _ = rig
        badge.moved.emit(120, 340)
        assert (cfg.ui.mic_badge_x, cfg.ui.mic_badge_y) == (120, 340)
        assert settings.saves == 1

    def test_dragging_does_not_notify_subsystems(self, rig):
        """位置只关这一个按钮的事,不该惊动引擎、热键那些 ——
        所以走 `save()` 而不是 `update()`。"""
        badge, settings, _, _ = rig
        badge.moved.emit(10, 20)
        assert settings.saves == 1        # save 而不是 update

    def test_position_survives_a_reapply(self, rig):
        """拖完之后配置再下发一次,不该把它弹回原处。"""
        badge, settings, cfg, placement = rig
        badge.moved.emit(700, 500)
        placement.apply(cfg)
        assert badge.moved_to == [(700, 500)]
