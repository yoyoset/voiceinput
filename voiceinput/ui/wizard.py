"""首次运行向导:按顺序把几个步骤翻一遍。

**为什么值得做一个向导**,而不是把这些丢进设置页让人自己找:

1. 没有模型时程序完全不能用,而模型要单独下 160MB。
2. 系统默认的输入设备经常不是话筒(虚拟声卡、立体声混音、各种 loopback
   都会占着默认位置)。选错的话表现是"按了热键没反应",用户会怪程序,
   不会想到是设备选错。
3. 热键要避开冲突 —— 而哪个组合空闲取决于这台机器装了什么,只能当场探测。

每一步自己拥有自己的控件、自己知道怎么写回配置(见 `steps/`)。
这个文件只管翻页:哪一步高亮、按钮显示什么、进出时该通知谁。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from .steps import DoneStep, HotkeyStep, MicStep, ModelStep, WelcomeStep
from .theme import Palette

STEPS = ["欢迎", "模型", "麦克风", "热键", "完成"]


class Wizard(QDialog):
    """向导。所有耗时操作都交给外部 backend,自己不持有引擎。

    backend 需要提供:
      - is_engine_ready() -> bool
      - reload_engine()                     异步
      - transcribe_async(audio, sr, cb)     异步,cb(text | None, error | None)
    """

    finished_setup = Signal(object)   # Config

    def __init__(self, cfg: Config, palette: Palette, backend, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._palette = palette

        self.setWindowTitle("VoiceInput 设置向导")
        self.setMinimumSize(660, 560)

        self.welcome = WelcomeStep(palette)
        self.model = ModelStep(cfg, backend)
        self.mic = MicStep(cfg, palette, backend)
        self.hotkeys = HotkeyStep(cfg)
        # **不能叫 self.done** —— QDialog 自己有个 done() 方法,
        # 属性会把它顶掉,accept() 一调就抛 'DoneStep' object is not callable
        self.done_step = DoneStep(cfg)
        self.steps = [self.welcome, self.model, self.mic, self.hotkeys, self.done_step]

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_stepbar())

        self.stack = QStackedWidget()
        for step in self.steps:
            step.busyChanged.connect(self._on_step_busy)
            self.stack.addWidget(step)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 8)
        body_layout.addWidget(self.stack)
        root.addWidget(body, 1)

        root.addWidget(self._build_nav())
        self._goto(0)

    # ---- 框架 ----

    def _build_stepbar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("role", "card")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(6)
        self._step_labels: list[QLabel] = []
        for i, name in enumerate(STEPS):
            label = QLabel(f"{i + 1}. {name}")
            self._step_labels.append(label)
            layout.addWidget(label)
            if i < len(STEPS) - 1:
                arrow = QLabel("›")
                arrow.setProperty("role", "hint")
                layout.addWidget(arrow)
        layout.addStretch(1)
        return bar

    def _build_nav(self) -> QWidget:
        nav = QWidget()
        layout = QHBoxLayout(nav)
        layout.setContentsMargins(24, 10, 24, 18)
        self.btn_skip = QPushButton("跳过向导")
        self.btn_skip.clicked.connect(self._skip)
        self.btn_back = QPushButton("上一步")
        self.btn_back.clicked.connect(lambda: self._goto(self.stack.currentIndex() - 1))
        self.btn_next = QPushButton("下一步")
        self.btn_next.setProperty("role", "primary")
        self.btn_next.clicked.connect(self._next)
        layout.addWidget(self.btn_skip)
        layout.addStretch(1)
        layout.addWidget(self.btn_back)
        layout.addWidget(self.btn_next)
        return nav

    # ---- 翻页 ----

    def _goto(self, index: int) -> None:
        index = max(0, min(len(self.steps) - 1, index))
        current = self.stack.currentIndex()
        if current != index:
            # 占着麦克风/设备的步骤要在离开时放开
            self.steps[current].on_leave()
        self.stack.setCurrentIndex(index)
        # 切页后 Qt 会把焦点丢给新页面里第一个能接受焦点的控件 —— 如果那
        # 恰好是热键那个 HotkeyEdit,它的 focusInEvent 会把已经选好的组合键
        # 显示替换成"按下组合键…",看起来像是空的、还没设置一样,
        # 而用户压根没点过它。焦点明确交给主操作按钮,不留给 Qt 猜。
        self.btn_next.setFocus()

        for i, label in enumerate(self._step_labels):
            if i < index:
                color, weight = self._palette.accent, "600"
            elif i == index:
                color, weight = self._palette.accent, "700"
            else:
                color, weight = self._palette.text_dim, "400"
            label.setStyleSheet(f"color: {color}; font-weight: {weight};")

        self.btn_back.setVisible(index > 0)
        self.btn_skip.setVisible(index < len(self.steps) - 1)
        self.btn_next.setText("完成" if index == len(self.steps) - 1 else "下一步")

        if self.steps[index] is self.done_step:
            # 摘要每行由拥有那个设置的步骤自己给
            rows = [row for step in self.steps for row in step.summary_rows()]
            self.done_step.fill(rows)
        self.steps[index].on_enter()

    def _next(self) -> None:
        index = self.stack.currentIndex()
        if index == len(self.steps) - 1:
            self._commit()
            self.accept()
            return
        self._goto(index + 1)

    def _skip(self) -> None:
        self._commit()
        self.accept()

    def _on_step_busy(self, busy: bool) -> None:
        """某一步在做不能被打断的事(下载模型),别让人翻页翻走。"""
        self.btn_next.setEnabled(not busy)

    # ---- 收尾 ----

    def _commit(self) -> None:
        for step in self.steps:
            step.on_leave()
            step.apply_to(self._cfg)
        self.finished_setup.emit(self._cfg)

    def closeEvent(self, event) -> None:  # noqa: N802
        for step in self.steps:
            step.shutdown()
        super().closeEvent(event)
