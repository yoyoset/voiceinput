"""UI 冒烟测试。用 offscreen 平台跑,不会真的在桌面上弹窗。

这类测试抓不到"好不好看",但能抓到样式表语法错误、控件构造异常、
信号连接写错名字这些一跑就炸的问题——这些占 UI bug 的大多数。
"""

import pytest

from voiceinput.config import Config
from voiceinput.history import History
from voiceinput.ui import theme
from voiceinput.ui.hotkey_edit import HotkeyEdit
from voiceinput.ui.icons import mic_icon, state_icon
from voiceinput.ui.main_window import MainWindow
from voiceinput.ui.overlay import Overlay
from voiceinput.ui.tray import Tray
from voiceinput.ui.widgets import Card, LevelBar


class TestTheme:
    @pytest.mark.parametrize("name", ["light", "dark"])
    def test_stylesheet_builds(self, qapp, name):
        p = theme.LIGHT if name == "light" else theme.DARK
        css = theme.stylesheet(p)
        assert "QPushButton" in css
        assert p.accent in css

    def test_apply(self, qapp):
        p = theme.apply_theme(qapp, "dark")
        assert p.is_dark
        assert qapp.styleSheet()

    def test_no_unresolved_placeholders(self, qapp):
        """f-string 里漏写变量会留下花括号,样式表就静默失效了。"""
        css = theme.stylesheet(theme.DARK)
        # Qt 样式表本身用 {} 做块,只检查不该出现的裸标识符占位
        assert "{p." not in css


class TestIcons:
    def test_mic_icon(self, qapp):
        assert not mic_icon("#22C55E").isNull()

    @pytest.mark.parametrize(
        "state", ["idle", "recording", "busy", "error", "loading"]
    )
    def test_state_icons(self, qapp, state):
        icon = state_icon(state, "#22C55E", "#F87171", "#94A69B")
        assert not icon.isNull()


class TestWidgets:
    def test_card(self, qapp):
        from PySide6.QtWidgets import QLabel

        c = Card("标题")
        c.add(QLabel("内容"))
        assert c.property("role") == "card"

    def test_hotkey_edit_roundtrip(self, qapp):
        e = HotkeyEdit("<ctrl>+<cmd>")
        assert e.spec() == "<ctrl>+<cmd>"
        assert e.text() == "Ctrl + Win"

    def test_hotkey_edit_empty(self, qapp):
        assert HotkeyEdit("").spec() == ""

    def test_level_bar_silence(self, qapp):
        bar = LevelBar()
        bar.set_level(float("-inf"))
        assert bar.is_silent

    def test_level_bar_loud(self, qapp):
        bar = LevelBar()
        bar.set_level(-20.0)
        assert not bar.is_silent


class TestOverlay:
    def test_states(self, qapp):
        o = Overlay(theme.DARK)
        o.show_recording("正在聆听")
        o.set_level(-25.0)
        o.show_busy("识别中")
        o.show_result("把这个 function 改成 async")
        o.show_error("只录到静音")
        o.hide()

    def test_level_mapping(self, qapp):
        o = Overlay(theme.DARK)
        o.set_level(float("-inf"))
        assert o._level == 0.0
        o.set_level(0.0)
        assert o._level == 1.0
        o.set_level(-60.0)
        assert o._level == 0.0

    def test_corners(self, qapp):
        o = Overlay(theme.LIGHT)
        for corner in ["bottom_right", "bottom_left", "top_right", "top_center"]:
            o.set_corner(corner)


class TestTray:
    def test_states(self, qapp):
        t = Tray(theme.DARK)
        for state in ["loading", "ready", "recording", "busy", "error"]:
            t.set_state(state, f"状态 {state}")
        assert not t.is_paused


class TestMainWindow:
    def test_builds_all_tabs(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]
        assert titles == ["常规", "音频", "引擎", "词典", "历史", "关于"]
        h.close()

    def test_collect_reflects_edits(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.general.hk_paste.set_spec("<ctrl>+<alt>+d")
        w.engine.threads.setValue(12)
        w.engine.use_itn.setChecked(False)
        cfg = w.collect()
        assert cfg.hotkey.paste == "<ctrl>+<alt>+d"
        assert cfg.engine.num_threads == 12
        assert cfg.engine.use_itn is False
        h.close()

    def test_dictionary_roundtrip(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        cfg = Config()
        cfg.replacements = {"keyper": "keytyper"}
        w = MainWindow(cfg, theme.DARK, h)
        assert w.dictionary.dict_table.rowCount() == 1
        assert w.collect().replacements == {"keyper": "keytyper"}
        h.close()

    def test_history_tab_lists_entries(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        h.add("第一条", "", 1.0, 0.1)
        h.add("第二条", "", 1.0, 0.1)
        w = MainWindow(Config(), theme.DARK, h)
        w.history.reload()
        assert w.history.hist_table.rowCount() == 2
        assert w.history.hist_table.item(0, 1).text() == "第二条"
        h.close()

    def test_model_status(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.set_model_status(False, "模型文件缺失")
        assert w.engine.model_status.property("role") == "danger"
        w.set_model_status(True, "已加载")
        assert w.engine.model_status.property("role") == "hint"
        h.close()


class TestAboutTab:
    """「关于」页是出问题时用户唯一能自助的地方,内容必须齐。"""

    def paths_text(self, window) -> str:
        from PySide6.QtWidgets import QLabel

        return "\n".join(
            w.text() for w in window.findChildren(QLabel)
            if w.property("role") == "mono"
        )

    def test_lists_log_path(self, qapp, tmp_path):
        """出问题最该看的就是日志 —— 之前这一条恰恰漏了。"""
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.tabs.setCurrentIndex(5)
        assert "voiceinput.log" in self.paths_text(w)
        h.close()

    def test_lists_all_footprint_paths(self, qapp, tmp_path):
        """程序在磁盘上留下的每一样东西都要列出来,否则"删掉即卸载"没法执行。"""
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.tabs.setCurrentIndex(5)
        text = self.paths_text(w)
        for expected in ["config.toml", "history.db", "voiceinput.log", "VoiceInput.lnk"]:
            assert expected in text, expected
        h.close()

    def test_open_log_when_missing_does_not_crash(self, qapp, tmp_path, monkeypatch):
        """日志还没生成时要给提示,不能静默什么都不发生。"""
        from PySide6.QtWidgets import QMessageBox

        shown = []
        monkeypatch.setattr(QMessageBox, "information",
                            lambda *a, **k: shown.append(a[-1]))
        monkeypatch.setattr("voiceinput.ui.pages.about.app_dir", lambda: tmp_path)

        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.about.open_log()
        assert shown and "还没生成" in shown[0]
        h.close()


class TestHistoryControls:
    """历史会记下说过的每一句话,但这些开关本来只存在于 config.toml 里,
    界面上完全没有 —— 等于"想关掉得先知道有个配置文件"。"""

    def test_settings_exposed(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        cfg = Config()
        cfg.history.enabled = False
        cfg.history.max_entries = 500
        w = MainWindow(cfg, theme.DARK, h)
        assert w.history.hist_enabled.isChecked() is False
        assert w.history.hist_max.value() == 500
        h.close()

    def test_settings_round_trip(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.history.hist_enabled.setChecked(False)
        w.history.hist_max.setValue(123)
        cfg = w.collect()
        assert cfg.history.enabled is False
        assert cfg.history.max_entries == 123
        h.close()

    def test_max_disabled_when_off(self, qapp, tmp_path):
        """关掉记录后,"最多保留多少条"就没有意义了。"""
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.history.hist_enabled.setChecked(False)
        assert not w.history.hist_max.isEnabled()
        h.close()

    def test_delete_selected_removes_one_entry(self, qapp, tmp_path):
        """之前只能清空全部 —— 说了不想留的一句话,得把整个历史都毁掉。"""
        h = History(path=tmp_path / "h.db")
        h.add("留着的", "", 1.0, 0.1)
        h.add("要删的", "", 1.0, 0.1)
        w = MainWindow(Config(), theme.DARK, h)
        w.history.reload()
        w.history.hist_table.selectRow(0)          # 最新的那条 = "要删的"
        w.history._delete_selected()
        assert [e.text for e in h.recent()] == ["留着的"]
        assert w.history.hist_table.rowCount() == 1
        h.close()

    def test_delete_without_selection_is_safe(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        h.add("还在", "", 1.0, 0.1)
        w = MainWindow(Config(), theme.DARK, h)
        w.history.reload()
        w.history.hist_table.clearSelection()
        w.history._delete_selected()
        assert h.count() == 1
        h.close()

    def test_set_history_to_none_clears_table(self, qapp, tmp_path):
        """关掉历史之后表格不能还留着旧内容。"""
        h = History(path=tmp_path / "h.db")
        h.add("旧的", "", 1.0, 0.1)
        w = MainWindow(Config(), theme.DARK, h)
        w.history.reload()
        assert w.history.hist_table.rowCount() == 1
        w.set_history(None)
        assert w.history.hist_table.rowCount() == 0
        h.close()


class TestDelaySettings:
    """两个等待时间都得能改。

    `send_delay_ms` 原来只存在于 config.toml 里 —— 而它太短会让回车
    赶在文字落地之前触发,把空的或残缺的内容提交出去。
    对着 Claude Code 连续说话正是这个工具的主场景。
    """

    def test_send_delay_exposed(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        cfg = Config()
        cfg.output.send_delay_ms = 250
        w = MainWindow(cfg, theme.DARK, h)
        assert w.general.out_send_delay.value() == 250
        h.close()

    def test_send_delay_round_trip(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.general.out_send_delay.setValue(400)
        assert w.collect().output.send_delay_ms == 400
        h.close()

    def test_preview_ms_round_trip(self, qapp, tmp_path):
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        w.general.ui_preview.setValue(0)
        assert w.collect().ui.preview_ms == 0
        h.close()

    def test_delays_have_sane_floors(self, qapp, tmp_path):
        """等待时间设成 0 会让粘贴几乎必然出错,不给这个选项。"""
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        assert w.general.out_paste_delay.minimum() >= 10
        assert w.general.out_send_delay.minimum() >= 10
        h.close()

    def test_preview_may_be_zero(self, qapp, tmp_path):
        """结果停留可以是 0(不显示成功提示),但失败提示不受它影响。"""
        h = History(path=tmp_path / "h.db")
        w = MainWindow(Config(), theme.DARK, h)
        assert w.general.ui_preview.minimum() == 0
        h.close()
