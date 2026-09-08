"""把界面渲染成 PNG 看效果,窗口不会弹到桌面上。

**必须用真实的 windows 平台,不能用 QT_QPA_PLATFORM=offscreen**:
offscreen 平台加载到的字体族数量是 0,中文全渲染成豆腐块,
截图会误导人以为程序有字体问题(实测 windows 平台下 333 个字体族,
Microsoft YaHei UI 正常)。

不弹窗靠的是**不调 show()**:QWidget.grab() 会强制布局并渲染到位图,
不需要窗口真的可见。

用法:
    uv run python bench/render_ui.py
输出到 bench/shots/。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from voiceinput.config import Config  # noqa: E402
from voiceinput.history import History  # noqa: E402
from voiceinput.ui import theme  # noqa: E402
from voiceinput.ui.main_window import MainWindow  # noqa: E402
from voiceinput.ui.mic_badge import MicBadge  # noqa: E402
from voiceinput.ui.overlay import Overlay  # noqa: E402
from voiceinput.ui.steps import CALIBRATION_PHRASE  # noqa: E402
from voiceinput.ui.wizard import Wizard  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).parent / "shots"


def sample_config() -> Config:
    """填一点真实数据,空界面看不出效果。"""
    cfg = Config()
    cfg.replacements = {
        "keyper": "keytyper",
        "P test": "pytest",
        "aniggo": "enigo",
        "hodkey": "hotkey",
    }
    return cfg


def seed_history(h: History) -> None:
    rows = [
        ("把这个 function 改成 async,再跑一遍 pytest", 5.0, 0.29),
        ("帮我看一下 keytyper 项目的依赖,enigo 是什么版本", 5.6, 0.31),
        ("我想做一个语音输入的工具,按住热键说话,松开之后文字直接出现在光标位置", 8.8, 0.48),
        ("把超时改成 30 秒,采样率用 16000 赫兹,单声道就够了", 7.1, 0.39),
        ("这个 commit 先别 push,我要改一下 config 里的 hotkey", 5.3, 0.32),
        ("打开那个文件看一下", 2.1, 0.13),
    ]
    for text, audio_s, infer_s in rows:
        h.add(text, text, audio_s, infer_s, "sensevoice")


def shoot(widget, name: str) -> None:
    widget.grab().save(str(OUT / name))
    print(f"  {name}")


def render(app: QApplication, mode: str) -> None:
    palette = theme.apply_theme(app, mode)
    db = OUT / f"_{mode}.db"
    db.unlink(missing_ok=True)
    history = History(path=db)
    seed_history(history)

    window = MainWindow(sample_config(), palette, history)
    window.resize(700, 640)
    window.set_status("ready", "就绪", "Ctrl + Win 说话粘贴 · Ctrl + Shift + Win 粘贴并发送")
    window.set_model_status(True, "已加载:sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17")
    # 刻意不 show():grab() 自己会把布局跑完,窗口不会出现在桌面上

    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        if window.tabs.tabText(i) == "历史":
            window._reload_history()
        app.processEvents()
        shoot(window, f"{mode}-{i}-{window.tabs.tabText(i)}.png")

    # 音频页的电平表要有数据才看得出样子
    window.tabs.setCurrentIndex(1)
    window.picker.bar.set_level(-22.0)
    window.picker.hint.setText("-22 dBFS —— 有信号")
    app.processEvents()
    shoot(window, f"{mode}-audio-active.png")

    # 热键冲突提示的样子:把两个热键设成同一个组合
    window.tabs.setCurrentIndex(0)
    window.hk_send.set_spec(window.hk_paste.spec())
    window._refresh_hotkey_problems()
    app.processEvents()
    shoot(window, f"{mode}-general-hotkey-conflict.png")

    window.close()
    history.close()

    # 向导。用假 backend,不碰真模型和麦克风。
    class _Backend:
        def is_engine_ready(self): return True
        def reload_engine(self): pass
        def transcribe_async(self, audio, sr, cb): cb(CALIBRATION_PHRASE, None)

    wizard = Wizard(sample_config(), palette, _Backend())
    wizard.resize(680, 580)
    for i, name in enumerate(["欢迎", "模型", "麦克风", "热键", "完成"]):
        wizard._goto(i)
        if name == "麦克风":
            wizard.picker.bar.set_level(-22.0)
            wizard.picker.hint.setText("-22 dBFS —— 有信号")
            wizard.mic.result.setText(f"识别结果:{CALIBRATION_PHRASE}")
            wizard._verdict(True, "完全正确,麦克风没问题")
        app.processEvents()
        shoot(wizard, f"{mode}-wizard-{i}-{name}.png")
    wizard._stop_level()
    wizard.close()
    db.unlink(missing_ok=True)

    # 悬浮麦克风的几个状态
    for state, level in [("idle", None), ("recording", -22.0),
                         ("busy", None), ("error", None), ("paused", None)]:
        b = MicBadge(palette)
        b.set_state(state)
        if level is not None:
            b.set_level(level)
        app.processEvents()
        shoot(b, f"{mode}-badge-{state}.png")
        b.close()

    # 悬浮条的几个状态。
    # 直接写内部状态而不调 show_xxx():那些方法会真的把窗口显示出来,
    # 截个图而已,没必要在用户桌面上闪一下。
    for state, message, level, note in [
        ("recording", "正在聆听", -24.0, ""),
        ("recording-long", "正在聆听", -24.0, "104s / 上限 120s"),
        ("busy", "识别中…", None, ""),
        ("result", "把这个 function 改成 async,再跑一遍 pytest", None, ""),
        ("warning", "超过 120 秒上限,后面的话没录进去 —— 已粘贴识别到的部分", None, ""),
        ("error", "只录到静音,检查麦克风设备是否选对", None, ""),
    ]:
        overlay = Overlay(palette)
        overlay._state = state.split("-")[0]
        overlay._message = message
        overlay._note = note
        if level is not None:
            overlay.set_level(level)
        app.processEvents()
        shoot(overlay, f"{mode}-overlay-{state}.png")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for mode in ("dark", "light"):
        print(f"[{mode}]")
        render(app, mode)
    print(f"\n输出目录: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
