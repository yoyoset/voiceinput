"""配置变更防抖。

不加防抖的话,拖一次数字框会连续发几十次 configChanged。写盘本身很快
(实测 0.44ms),但「引擎」页的线程数每变一步会触发一次**完整模型重载**
(每次约 3 秒),从 8 拖到 16 就是 8 次重载排队。
"""

import pytest

from voiceinput.config import Config
from voiceinput.history import History
from voiceinput.ui import theme
from voiceinput.ui.main_window import MainWindow


@pytest.fixture
def window(qapp, tmp_path):
    h = History(path=tmp_path / "h.db")
    cfg = Config()
    cfg.replacements = {"keyper": "keytyper"}
    w = MainWindow(cfg, theme.DARK, h)
    yield w
    w.close()
    h.close()


def emitted(window) -> list:
    got = []
    window.configChanged.connect(got.append)
    return got


class TestDebounce:
    def test_rapid_changes_do_not_emit_immediately(self, window):
        """连续改动期间一次都不该发出去。"""
        got = emitted(window)
        for v in range(80, 201, 5):
            window.general.out_paste_delay.setValue(v)
        assert got == []

    def test_flush_emits_once(self, window):
        """几十次改动合并成一次。"""
        got = emitted(window)
        for v in range(80, 201, 5):
            window.general.out_paste_delay.setValue(v)
        window.flush_pending()
        assert len(got) == 1

    def test_flushed_value_is_the_last_one(self, window):
        got = emitted(window)
        for v in (100, 150, 200):
            window.general.out_paste_delay.setValue(v)
        window.flush_pending()
        assert got[-1].output.paste_delay_ms == 200

    def test_threads_change_coalesces(self, window):
        """线程数是最要命的那个:每次发出都意味着一次 3 秒的模型重载。"""
        got = emitted(window)
        for v in range(8, 17):
            window.engine.threads.setValue(v)
        window.flush_pending()
        assert len(got) == 1
        assert got[0].engine.num_threads == 16

    def test_flush_without_pending_is_noop(self, window):
        """没有待发的改动时 flush 不该凭空发一次。"""
        got = emitted(window)
        window.flush_pending()
        assert got == []

    def test_close_flushes(self, window):
        """改完就关窗口,那次改动不能丢。"""
        got = emitted(window)
        window.general.out_paste_delay.setValue(321)
        window.close()
        assert len(got) == 1
        assert got[0].output.paste_delay_ms == 321

    def test_timer_actually_fires(self, qapp, window):
        """防抖到期后要真的自己发出去,不能只靠 flush。"""
        from PySide6.QtCore import QEventLoop, QTimer

        got = emitted(window)
        window.general.out_paste_delay.setValue(199)

        loop = QEventLoop()
        QTimer.singleShot(600, loop.quit)
        loop.exec()

        assert len(got) == 1
        assert got[0].output.paste_delay_ms == 199


class TestImmediateFeedback:
    def test_hotkey_problems_update_without_waiting(self, window):
        """热键冲突是本地反馈,要立刻标红,不能等 300ms。"""
        window.general.hk_send.set_spec(window.general.hk_paste.spec())
        window.general.emit_changed()
        assert window.general.hk_problems.isVisible() or window.general.hk_problems.text()

    def test_problems_clear_when_fixed(self, window):
        window.general.hk_send.set_spec(window.general.hk_paste.spec())
        window.general.emit_changed()
        assert window.general.hk_problems.text()
        window.general.hk_send.set_spec("<ctrl>+<alt>+<enter>")
        window.general.emit_changed()
        assert not window.general.hk_problems.text()


class TestLoadingGuard:
    def test_no_emit_while_loading(self, window):
        """初始化填值阶段不能触发保存。"""
        got = emitted(window)
        window.general._loading = True
        window.general.out_paste_delay.setValue(456)
        window.general._loading = False
        window.flush_pending()
        assert got == []
