"""换主题时谁需要被通知。

以前这份名单只存在于配置分发里那个 `if cfg.ui.theme != old.ui.theme`
分支内。新加一个带配色的控件,得记得回去那个 if 里补一行 ——
漏了的表现是**换主题之后有一个控件还是旧颜色**,而且不报错。
"""

import pytest

from voiceinput.config import Config
from voiceinput.ui.theming import Theme


@pytest.fixture
def theme(qapp):
    cfg = Config()
    cfg.ui.theme = "dark"
    return Theme(qapp, cfg)


class TestPalette:
    def test_has_a_palette_from_the_start(self, theme):
        assert theme.palette is not None

    def test_palette_changes_with_the_theme(self, theme):
        before = theme.palette
        cfg = Config()
        cfg.ui.theme = "light"
        theme.apply(cfg)
        assert theme.palette is not before


class TestWatchers:
    def test_all_watchers_are_told(self, theme):
        """名单在一处 —— 这就是这个类存在的理由。"""
        seen = [[], [], []]
        theme.watch(seen[0].append, seen[1].append, seen[2].append)
        cfg = Config()
        cfg.ui.theme = "light"
        theme.apply(cfg)
        assert all(len(s) == 1 for s in seen)
        assert all(s[0] is theme.palette for s in seen)

    def test_no_change_tells_nobody(self, theme):
        """重算样式表不便宜,而配置保存是防抖后批量发的。"""
        seen = []
        theme.watch(seen.append)
        cfg = Config()
        cfg.ui.theme = "dark"          # 和 fixture 里的一样
        theme.apply(cfg)
        assert seen == []

    def test_switching_back_and_forth_tells_each_time(self, theme):
        seen = []
        theme.watch(seen.append)
        for name in ("light", "dark", "light"):
            cfg = Config()
            cfg.ui.theme = name
            theme.apply(cfg)
        assert len(seen) == 3

    def test_unrelated_change_tells_nobody(self, theme):
        seen = []
        theme.watch(seen.append)
        cfg = Config()
        cfg.ui.theme = "dark"
        cfg.engine.num_threads = 12
        theme.apply(cfg)
        assert seen == []

    def test_watchers_registered_later_still_get_told(self, theme):
        early, late = [], []
        theme.watch(early.append)
        theme.watch(late.append)
        cfg = Config()
        cfg.ui.theme = "light"
        theme.apply(cfg)
        assert len(early) == 1 and len(late) == 1

    def test_callbacks_not_widgets(self, theme):
        """收回调而不是控件:主窗口的方法叫 apply_palette,悬浮条叫
        set_palette —— 靠 getattr 猜名字只会在某天悄悄漏掉一个。"""
        calls = []

        class WeirdlyNamed:
            def repaint_yourself(self, palette):
                calls.append(palette)

        widget = WeirdlyNamed()
        theme.watch(widget.repaint_yourself)
        cfg = Config()
        cfg.ui.theme = "light"
        theme.apply(cfg)
        assert len(calls) == 1
