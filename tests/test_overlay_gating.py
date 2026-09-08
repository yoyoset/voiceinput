"""关掉提示条,关掉的只是顺利时的那些提示 —— 失败提示照常显示。

这条不对称是这个悬浮条存在的理由的直接推论:它不是为了好看,是为了
**排除"后台失败但用户以为成功"**。用户嫌它烦而关掉,关的是"正在聆听""识别中"
这些顺利时的噪音;麦克风打不开、只录到静音这些,关了也得说。

规矩原来靠调用方记着(五处 `if show_overlay:` 守着成功类、失败类故意不守),
迟早有一处漏掉或者多守。现在归 Overlay 自己,这里钉住它。
"""

import pytest

from voiceinput.config import Config
from voiceinput.ui import theme
from voiceinput.ui.overlay import Overlay


def make(qapp, *, enabled=True, preview_ms=1200):
    cfg = Config()
    cfg.ui.show_overlay = enabled
    cfg.ui.preview_ms = preview_ms
    overlay = Overlay(theme.DARK)
    overlay.apply(cfg)
    return overlay


class TestDisabled:
    @pytest.mark.parametrize("call", [
        lambda o: o.show_recording("正在聆听"),
        lambda o: o.show_busy("识别中"),
        lambda o: o.show_result("一句话"),
        lambda o: o.show_cancelled(),
    ])
    def test_success_messages_are_suppressed(self, qapp, call):
        overlay = make(qapp, enabled=False)
        call(overlay)
        assert overlay._state == "idle", "关掉之后不该进入任何显示态"
        overlay.close()

    @pytest.mark.parametrize("call, state", [
        (lambda o: o.show_error("麦克风打不开"), "error"),
        (lambda o: o.show_warning("录音被截断"), "warning"),
    ])
    def test_failures_are_shown_anyway(self, qapp, call, state):
        """**这条是重点。** 关掉提示条不等于同意静默失败。"""
        overlay = make(qapp, enabled=False)
        call(overlay)
        assert overlay._state == state
        overlay.close()


class TestEnabled:
    def test_success_messages_go_through(self, qapp):
        overlay = make(qapp)
        overlay.show_recording("正在聆听")
        assert overlay._state == "recording"
        overlay.close()

    def test_result_respects_preview_duration(self, qapp):
        overlay = make(qapp, preview_ms=800)
        overlay.show_result("一句话")
        assert overlay._state == "result"
        assert overlay._hide_timer.interval() == 800
        overlay.close()

    def test_zero_preview_shows_nothing(self, qapp):
        """停留时间设成 0 = 不显示结果。**不能显示 0 毫秒** ——
        那会闪一下再消失,比不显示更烦人。"""
        overlay = make(qapp, preview_ms=0)
        overlay.show_result("一句话")
        assert overlay._state == "idle"
        overlay.close()

    def test_zero_preview_still_shows_failures(self, qapp):
        overlay = make(qapp, preview_ms=0)
        overlay.show_error("只录到静音")
        assert overlay._state == "error"
        overlay.close()

    def test_cancelled_goes_through(self, qapp):
        """取消不是失败,但也不该被「结果停留 = 0」这个开关连累 ——
        它走的是自己固定的 1500ms,不受 `preview_ms` 影响。"""
        overlay = make(qapp, preview_ms=0)
        overlay.show_cancelled()
        assert overlay._state == "cancelled"
        assert overlay._hide_timer.interval() == 1500
        overlay.close()


class TestApply:
    def test_turning_it_off_hides_it_now(self, qapp):
        """正显示着的时候被关掉,应该马上消失,而不是等它自己超时。"""
        overlay = make(qapp)
        overlay.show_recording("正在聆听")
        cfg = Config()
        cfg.ui.show_overlay = False
        overlay.apply(cfg)
        assert not overlay.isVisible()
        overlay.close()

    def test_corner_comes_from_config(self, qapp):
        overlay = Overlay(theme.DARK)
        cfg = Config()
        cfg.ui.overlay_corner = "top_center"
        overlay.apply(cfg)
        assert overlay._corner == "top_center"
        overlay.close()
