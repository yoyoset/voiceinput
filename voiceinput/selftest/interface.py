"""界面画得出来吗,文字送得出去吗。

只创建 QApplication 是不够的:打包时砍掉了 opengl32sw.dll 和一批 Qt DLL,
那些要到真正构造控件、应用样式表、自绘图标时才会暴露。
所以这里把每个分页、向导每一步都用 `grab()` 真的画一遍
(不调 `show()`,不会弹窗打扰用户)。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .. import config as config_mod
from .report import Report

CLIPBOARD_PROBE = "VoiceInput 自检 · 中英混合 test 123"


def check_qt(report: Report):
    """Qt 起不起得来,中文字形在不在。返回 QApplication,失败返回 None。"""
    try:
        from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        families = QFontDatabase.families()
        has_cjk = QFontMetrics(QFont("Microsoft YaHei UI")).inFont("你")
        report.verdict(has_cjk, f"Qt 就绪,{len(families)} 个字体族,"
                                f"中文字形 {'可用' if has_cjk else '缺失'}")
        return app
    except Exception as e:
        report.failed(f"Qt: {e}")
        return None


def check_clipboard(report: Report, app) -> None:
    """剪贴板往返。

    这是**每次听写的最后一步** —— 文字就是靠它送出去的。
    前面全过、这里坏了,表现是"识别完了但什么都没粘出来"。
    只测剪贴板本身;发 Ctrl+V 需要一个焦点窗口,那部分没法在自检里安全验证。
    """
    try:
        clip = app.clipboard()
        previous = clip.text()
        clip.setText(CLIPBOARD_PROBE)
        got = clip.text()
        clip.setText(previous)      # 不能吞掉用户原有的剪贴板内容
        if got == CLIPBOARD_PROBE:
            report.passed("剪贴板读写正常(含中文)")
        else:
            report.failed(f"剪贴板写进去的读不回来:{got!r}")
    except Exception as e:
        report.failed(f"剪贴板: {e}")


def check_render(report: Report, app) -> None:
    try:
        from ..history import History
        from ..ui.theme import apply_theme

        palette = apply_theme(app, "dark")
        with tempfile.TemporaryDirectory() as tmp:
            history = History(path=Path(tmp) / "selftest.db")
            try:
                blank, wizard_pages, tabs = _render_all(app, palette, history)
            finally:
                # **必须 finally。** 之前 close() 写在顺序流末尾,中间任何一个
                # 异常都会让 sqlite 句柄开着走到 TemporaryDirectory 的清理,
                # 于是抛出「WinError 32 文件被占用」—— 把**真正的错误盖掉了**。
                # 实测就这么发生过一次:真错是 AttributeError,
                # 报出来的却是文件占用。
                history.close()

        if blank:
            report.failed(f"界面渲染:{blank} 个画面是空的")
        else:
            report.passed(f"界面渲染正常({tabs} 个分页 + "
                          f"{wizard_pages} 步向导 + 悬浮条)")
    except Exception as e:
        report.failed(f"界面渲染: {e}")


def _render_all(app, palette, history) -> tuple[int, int, int]:
    """把主窗口每个分页、向导每一步、悬浮条都真的画一遍。

    返回 (画不出来的画面数, 向导步数, 分页数)。
    """
    from ..ui.main_window import MainWindow
    from ..ui.overlay import Overlay
    from ..ui.wizard import Wizard

    class _StubBackend:
        def is_engine_ready(self): return True
        def reload_engine(self): pass
        def transcribe_async(self, audio, sr, cb): cb("", None)

    def looks_blank(widget) -> bool:
        app.processEvents()
        pm = widget.grab()
        return pm.isNull() or pm.width() < 100

    blank = 0
    window = MainWindow(config_mod.load(), palette, history)
    try:
        window.resize(700, 640)
        for i in range(window.tabs.count()):
            window.tabs.setCurrentIndex(i)
            blank += looks_blank(window)
        tabs = window.tabs.count()
    finally:
        window.close()

    overlay = Overlay(palette)
    overlay._state = "recording"
    overlay._message = "自检"
    blank += overlay.grab().isNull()

    # 向导也要验:它是独立的一套界面,主窗口画得出来不代表向导画得出来。
    wizard = Wizard(config_mod.load(), palette, _StubBackend())
    try:
        wizard.resize(680, 580)
        wizard_pages = wizard.stack.count()
        for i in range(wizard_pages):
            wizard._goto(i)
            blank += looks_blank(wizard)
    finally:
        # close() 会挨个通知每一步收摊 —— 标定那一步正占着麦克风
        wizard.close()

    return blank, wizard_pages, tabs
