"""「引擎」页:模型在哪、用什么算、加载成功没有。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from ...asr import providers
from ...config import Config, app_dir
from ..widgets import Card, ComboBox, hint, labeled, restyle, spin, wrap
from .base import Page


class EnginePage(Page):
    reloadRequested = Signal()
    downloadRequested = Signal()

    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent=parent)

        model = Card("模型")
        self.model_dir = QLineEdit(cfg.engine.model_dir)
        self.model_dir.editingFinished.connect(self.emit_changed)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.model_dir, 1)
        row.addWidget(browse)
        model.add_layout(labeled("模型目录", wrap(row)))

        self.model_status = QLabel("")
        self.model_status.setWordWrap(True)
        model.add(self.model_status)

        acts = QHBoxLayout()
        btn_reload = QPushButton("重新加载模型")
        btn_reload.setProperty("role", "primary")
        btn_reload.clicked.connect(self.reloadRequested.emit)
        btn_download = QPushButton("下载模型 / 重新标定…")
        btn_download.clicked.connect(self.downloadRequested.emit)
        acts.addWidget(btn_reload)
        acts.addWidget(btn_download)
        acts.addStretch(1)
        model.add_layout(acts)
        model.add(hint(
            "必须用 2024-07-17 原版 SenseVoice。2025-09-09 那个是粤语特化微调,"
            "中英日韩全线崩坏。"
        ))
        self.body.addWidget(model)

        perf = Card("推理")
        self.threads = spin(1, 32, cfg.engine.num_threads)
        self.threads.valueChanged.connect(self.emit_changed)
        perf.add_layout(labeled("线程数", self.threads))

        # **只列这台机器上真的能用的后端。**
        # 以前 CUDA 是无条件列出来的,而 CPU 版的 sherpa-onnx 拿到 cuda
        # 会静默回退 —— 界面写着 CUDA、实际跑在 CPU 上,没有任何提示。
        self.provider = ComboBox()
        usable = providers.available()
        self.provider.addItem("CPU", providers.CPU)
        if providers.CUDA in usable:
            self.provider.addItem("CUDA(显卡)", providers.CUDA)
        self.provider.setCurrentIndex(max(0, self.provider.findData(cfg.engine.provider)))
        self.provider.currentIndexChanged.connect(self.emit_changed)
        perf.add_layout(labeled("计算设备", self.provider))
        if providers.CUDA not in usable:
            perf.add(hint(
                "这个版本的 sherpa-onnx 只带了 CPU 后端,所以没有显卡这个选项 —— "
                "列出来也是选了没用(它会不声不响地退回 CPU)。"
            ))

        self.use_itn = QCheckBox("启用逆文本归一化(标点与阿拉伯数字)")
        self.use_itn.setChecked(cfg.engine.use_itn)
        self.use_itn.toggled.connect(self.emit_changed)
        perf.add(self.use_itn)

        # 这里以前写着开发机的实测数字(RTF 0.054 之类)。那是**那台机器**的
        # 成绩,对别人既不准也没用。改成显示这台机器刚刚跑出来的值。
        self.perf_status = QLabel("还没说过话,测不出这台机器有多快。")
        self.perf_status.setProperty("role", "hint")
        self.perf_status.setWordWrap(True)
        perf.add(self.perf_status)
        self.body.addWidget(perf)

        self.body.addStretch(1)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择模型目录", str(app_dir()))
        if path:
            self.model_dir.setText(path)
            self.emit_changed()

    def set_model_status(self, ok: bool, message: str) -> None:
        self.model_status.setText(message)
        self.model_status.setProperty("role", "hint" if ok else "danger")
        restyle(self.model_status)

    def set_measured(self, infer_seconds: float, audio_seconds: float) -> None:
        """报告这台机器刚刚的一次真实推理耗时。

        **这是界面上唯一的性能来源。** 开发机的数字对别人没有意义,
        而用户真正想知道的是"我这台跑得动吗" —— 只有实际跑一次能回答。
        """
        if audio_seconds <= 0:
            return
        rtf = infer_seconds / audio_seconds
        speed = (1 / rtf) if rtf else 0.0
        self.perf_status.setText(
            f"这台机器实测:{audio_seconds:.1f} 秒的话 {infer_seconds:.2f} 秒转完"
            f"(RTF {rtf:.3f},约 {speed:.0f} 倍实时),"
            f"{self.threads.value()} 线程 / {self.provider.currentText()}。"
        )

    # ---- 写回 ----

    def collect(self, cfg: Config) -> None:
        cfg.engine.model_dir = self.model_dir.text().strip()
        cfg.engine.num_threads = self.threads.value()
        cfg.engine.provider = self.provider.currentData()
        cfg.engine.use_itn = self.use_itn.isChecked()
