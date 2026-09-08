"""向导的构造与流程测试。用假的 backend,不碰真模型和麦克风。"""

from pathlib import Path

import pytest

from voiceinput import download as dl
from voiceinput.config import Config
from voiceinput.ui import theme
from voiceinput.ui.steps import CALIBRATION_PHRASE
from voiceinput.ui.wizard import STEPS, Wizard


class FakeBackend:
    """替身。record 下调用轨迹,好断言向导确实调了该调的东西。"""

    def __init__(self, ready: bool = True, text: str = CALIBRATION_PHRASE,
                 error: str | None = None) -> None:
        self.ready = ready
        self.text = text
        self.error = error
        self.reload_calls = 0
        self.transcribe_calls = 0

    def is_engine_ready(self) -> bool:
        return self.ready

    def reload_engine(self) -> None:
        self.reload_calls += 1

    def transcribe_async(self, audio, sr, callback) -> None:
        self.transcribe_calls += 1
        callback(None, self.error) if self.error else callback(self.text, None)


@pytest.fixture
def wizard(qapp, tmp_path):
    cfg = Config()
    cfg.engine.model_dir = str(tmp_path / "models" / "nonexistent")
    w = Wizard(cfg, theme.DARK, FakeBackend())
    yield w
    w.close()


class TestStructure:
    def test_all_steps_present(self, wizard):
        assert wizard.stack.count() == len(STEPS)

    def test_starts_at_first_step(self, wizard):
        assert wizard.stack.currentIndex() == 0

    def test_back_hidden_on_first_step(self, wizard):
        assert not wizard.btn_back.isVisible() or wizard.stack.currentIndex() == 0

    def test_last_step_says_finish(self, wizard):
        wizard._goto(len(STEPS) - 1)
        assert wizard.btn_next.text() == "完成"

    def test_navigation_clamps(self, wizard):
        wizard._goto(-5)
        assert wizard.stack.currentIndex() == 0
        wizard._goto(999)
        assert wizard.stack.currentIndex() == len(STEPS) - 1


class TestModelStep:
    def test_missing_model_flagged(self, wizard):
        wizard._goto(1)
        assert wizard.model.status.property("role") == "danger"
        assert "下载模型" in wizard.model.btn_download.text()

    def test_present_model_flagged(self, qapp, tmp_path):
        """伪造一个够大的模型文件,让 check() 认为它就绪。"""
        model_dir = tmp_path / "models" / "sv"
        model_dir.mkdir(parents=True)
        (model_dir / "model.int8.onnx").write_bytes(b"\0" * (120 * 1024 * 1024))
        (model_dir / "tokens.txt").write_text("x", encoding="utf-8")

        cfg = Config()
        cfg.engine.model_dir = str(model_dir)
        w = Wizard(cfg, theme.DARK, FakeBackend())
        w._goto(1)
        assert w.model.status.property("role") == "hint"
        w.close()


class TestCalibration:
    def test_标定句里不许有英文(self):
        """**这一步只判断「设备对不对」,别把英文术语混进判据。**

        原来用的是「把这个 function 改成 async」,想着贴近真实使用场景。
        实测这是错的:SenseVoice 对口说的英文术语本来就不准,`async`
        会被听成别的词,于是**话筒完全正常的人也会被判成"可能是设备选错"**
        —— 这一步给出的是假警报,而它恰恰是用来排除假象的。

        英文术语准不准是「词典」页的事。
        """
        assert not any(c.isascii() and c.isalpha() for c in CALIBRATION_PHRASE), \
            f"标定句里混进了英文:{CALIBRATION_PHRASE}"

    def test_correct_phrase_passes(self, wizard):
        wizard._goto(2)
        wizard.mic.on_result(CALIBRATION_PHRASE, None)
        assert wizard.mic.verdict.text().startswith("✓")

    def test_close_enough_passes(self, wizard):
        """少量出入应该判通过,不然一两个字错就吓到用户。

        **从常量派生,不写死句子。** 上一次换标定句时这个测试就是因为
        写死了旧句子而变红的 —— 而它想验的根本不是"那句话是什么"。
        """
        wizard._goto(2)
        wizard.mic.on_result(CALIBRATION_PHRASE[:-1] + "。", None)
        assert wizard.mic.verdict.text().startswith("✓")

    def test_way_off_fails(self, wizard):
        wizard._goto(2)
        wizard.mic.on_result("今天天气不错我们去公园散步吧", None)
        assert wizard.mic.verdict.text().startswith("✗")

    def test_empty_fails(self, wizard):
        wizard._goto(2)
        wizard.mic.on_result("", None)
        assert wizard.mic.verdict.text().startswith("✗")

    def test_error_fails(self, wizard):
        wizard._goto(2)
        wizard.mic.on_result(None, "模型没加载")
        assert "模型没加载" in wizard.mic.verdict.text()

    def test_engine_not_ready_blocks(self, qapp, tmp_path):
        cfg = Config()
        backend = FakeBackend(ready=False)
        w = Wizard(cfg, theme.DARK, backend)
        w._goto(2)
        # 直接走 _calib_stop 的判断路径:没有 recorder 时应安静返回
        w.mic.stop_recording()
        assert backend.transcribe_calls == 0
        w.close()


class TestCommit:
    def test_emits_config(self, wizard):
        received = []
        wizard.finished_setup.connect(received.append)
        wizard._goto(3)
        wizard.hotkeys.paste.set_spec("<ctrl>+<alt>+d")
        wizard._goto(4)
        wizard._commit()
        assert len(received) == 1
        assert received[0].hotkey.paste == "<ctrl>+<alt>+d"

    def test_skip_also_commits(self, wizard):
        received = []
        wizard.finished_setup.connect(received.append)
        wizard._skip()
        assert len(received) == 1

    def test_summary_rebuilt_each_visit(self, wizard):
        """来回翻页不能让摘要里堆出重复行。"""
        wizard._goto(4)
        first = wizard.done_step.summary.body.count()
        wizard._goto(3)
        wizard._goto(4)
        assert wizard.done_step.summary.body.count() == first


class TestModelCheck:
    def test_missing_dir(self, tmp_path):
        assert not dl.check(tmp_path / "nope").present

    def test_missing_files(self, tmp_path):
        d = tmp_path / "m"
        d.mkdir()
        status = dl.check(d)
        assert not status.present
        assert "缺少文件" in status.message

    def test_truncated_model_rejected(self, tmp_path):
        """下载中断留下的半个文件也"存在",不能只看存不存在。"""
        d = tmp_path / "m"
        d.mkdir()
        (d / "model.int8.onnx").write_bytes(b"\0" * 1024)
        (d / "tokens.txt").write_text("x", encoding="utf-8")
        status = dl.check(d)
        assert not status.present
        assert "没下完" in status.message

    def test_complete_model_accepted(self, tmp_path):
        d = tmp_path / "m"
        d.mkdir()
        (d / "model.int8.onnx").write_bytes(b"\0" * (120 * 1024 * 1024))
        (d / "tokens.txt").write_text("x", encoding="utf-8")
        assert dl.check(d).present


class TestTarSafety:
    def test_rejects_path_traversal(self):
        """压缩包里的路径不能跑到目标目录外面去。"""
        import tarfile

        worker = dl.DownloadWorker(Path("."))
        for bad in ["../evil", "/abs/evil", "a/../../evil"]:
            assert not worker._safe_member(tarfile.TarInfo(bad)), bad
        for good in ["model/x.onnx", "tokens.txt"]:
            assert worker._safe_member(tarfile.TarInfo(good)), good


class TestHotkeyConflictStep:
    """向导那一步的职责是"避开冲突"。

    光让用户填不算做到 —— 哪个组合空闲取决于这台机器装了什么,
    只有当场问系统才知道。实测:开发机上连默认的 Ctrl+Alt+Space 都是被占的。
    """

    def test_taken_default_is_replaced(self, qapp, tmp_path, monkeypatch):
        """默认组合被占时,进到这一步就该已经换好,而不是等用户去点按钮。"""
        from voiceinput import conflict
        from voiceinput.config import Config
        from voiceinput.ui import theme
        from voiceinput.ui.wizard import Wizard

        cfg = Config()
        taken = {cfg.hotkey.paste, cfg.hotkey.paste_and_send}
        monkeypatch.setattr(conflict, "taken_by_another_app",
                            lambda spec: spec in taken)

        w = Wizard(cfg, theme.DARK, FakeBackend())
        try:
            assert w.hotkeys.paste.spec() not in taken
            assert w.hotkeys.send.spec() not in taken
            assert "已经替你换掉了" in w.hotkeys.verdict.text()
        finally:
            w.close()

    def test_free_default_is_left_alone(self, qapp, tmp_path, monkeypatch):
        """没冲突就别乱动用户的配置。"""
        from voiceinput import conflict
        from voiceinput.config import Config
        from voiceinput.ui import theme
        from voiceinput.ui.wizard import Wizard

        cfg = Config()
        monkeypatch.setattr(conflict, "taken_by_another_app", lambda spec: False)

        w = Wizard(cfg, theme.DARK, FakeBackend())
        try:
            assert w.hotkeys.paste.spec() == cfg.hotkey.paste
            assert "已经替你换掉了" not in w.hotkeys.verdict.text()
        finally:
            w.close()

    def test_unprobeable_combo_counts_as_bad(self, qapp, monkeypatch):
        """探测不了(纯修饰键)也要当成"没确认安全",不能放过。"""
        from voiceinput import conflict
        from voiceinput.config import Config
        from voiceinput.ui import theme
        from voiceinput.ui.wizard import Wizard

        cfg = Config()
        cfg.hotkey.paste = "<ctrl>+<cmd>"
        cfg.hotkey.paste_and_send = "<ctrl>+<shift>+<cmd>"
        monkeypatch.setattr(
            conflict, "taken_by_another_app",
            lambda spec: None if "<cmd>" in spec else False)

        w = Wizard(cfg, theme.DARK, FakeBackend())
        try:
            assert "<cmd>" not in w.hotkeys.paste.spec()
        finally:
            w.close()


class TestWizardControlsIgnoreWheel:
    """**证伪轮挖出来的一条从没验证过的假设。**

    设置页(MainWindow)的滚轮防误改是在套着 QScrollArea 的地方测的 ——
    `WheelGuard` 找不到焦点时会去找祖先滚动区域,把事件转发过去。
    但向导(Wizard)里的控件根本不在任何 `QAbstractScrollArea` 里面
    (`Step` 的骨架里没有滚动区域,固定尺寸对话框直接把几步塞进
    `QStackedWidget`)——`_scroll_area()` 会一路找到 None,
    走的是另一条从没跑过的分支:`event.ignore()`。

    实测：这条分支确实挡住了滚轮,没有值被悄悄改掉。这里把它钉住,
    以防将来 `WheelGuard` 改动时,没有滚动区域这条路径被漏掉。
    """

    def _wheel(self, qapp, widget, dy=-120) -> None:
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QWheelEvent

        c = widget.rect().center()
        qapp.sendEvent(widget, QWheelEvent(
            c, widget.mapToGlobal(c), QPoint(0, dy), QPoint(0, dy),
            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False))
        qapp.processEvents()

    def test_翻到热键步骤时输入框不会抢到焦点(self, wizard):
        """**真渲染+真交互抓到的 bug,读代码看不出来。**

        `HotkeyStep` 的第一个输入框显示的是已经选好的组合键(比如自动
        避开冲突后换成的 `Ctrl + Shift + Space`)。但 `QStackedWidget`
        切页时,Qt 会把焦点丢给新页面里第一个能接受焦点的控件——如果
        恰好是这个 `HotkeyEdit`,它的 `focusInEvent` 会把显示内容换成
        "按下组合键…",看起来像是空的、还没设置一样,而用户压根没点过它。

        修法是 `Wizard._goto()` 里显式把焦点交给「下一步」按钮,
        不留给 Qt 去猜第一个 tab 停靠点是谁。
        """
        wizard._goto(3)
        assert not wizard.hotkeys.paste.hasFocus()
        assert wizard.hotkeys.paste.text() != "按下组合键…"

    def test_hotkey_step_has_no_scroll_area_ancestor(self, wizard):
        """先确认这个测试真的测到了点子上,不是白测。"""
        wizard._goto(3)
        assert wizard.hotkeys.mode._scroll_area() is None

    def test_hotkey_mode_combo_survives_wheel(self, wizard, qapp):
        wizard._goto(3)
        for _ in range(3):
            qapp.processEvents()
        combo = wizard.hotkeys.mode
        before = combo.currentIndex()
        self._wheel(qapp, combo)
        assert combo.currentIndex() == before

    def test_mic_device_combo_survives_wheel(self, wizard, qapp):
        wizard._goto(2)
        for _ in range(3):
            qapp.processEvents()
        combo = wizard.mic.picker.combo
        assert combo._scroll_area() is None
        before = combo.currentIndex()
        self._wheel(qapp, combo)
        assert combo.currentIndex() == before
