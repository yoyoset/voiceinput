"""「音频」页:选设备、看电平、录音上限。"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton

from ...config import Config
from ..device_picker import DevicePicker, device_hint
from ..theme import Palette
from ..widgets import Card, DoubleSpinBox, hint, labeled
from .base import Page


class AudioPage(Page):
    def __init__(self, cfg: Config, palette: Palette, parent=None) -> None:
        super().__init__(parent=parent)

        dev = Card("输入设备")
        # 设备选择 + 电平的那套逻辑跟向导共用一份,见 device_picker。
        # 之前两边各写一份,提示文案已经漂移成两种措辞了。
        self.picker = DevicePicker(palette, cfg.audio.device)
        self.picker.deviceChanged.connect(self.emit_changed)
        dev.add(self.picker)

        btns = QHBoxLayout()
        self.btn_test = QPushButton("开始测试")
        self.btn_test.clicked.connect(self._toggle_test)
        btn_refresh = QPushButton("刷新设备列表")
        btn_refresh.clicked.connect(self.picker.reload_devices)
        btns.addWidget(self.btn_test)
        btns.addWidget(btn_refresh)
        btns.addStretch(1)
        dev.add_layout(btns)

        dev.add(hint(device_hint()))
        self.body.addWidget(dev)

        rec = Card("录音")
        self.max_seconds = DoubleSpinBox()
        self.max_seconds.setRange(5.0, 600.0)
        self.max_seconds.setSingleStep(10.0)
        self.max_seconds.setDecimals(0)
        self.max_seconds.setSuffix(" 秒")
        self.max_seconds.setValue(cfg.audio.max_seconds)
        self.max_seconds.valueChanged.connect(self.emit_changed)
        rec.add_layout(labeled("单次上限", self.max_seconds))
        rec.add(hint("防止热键卡住导致无限录音把内存吃满。"))
        self.body.addWidget(rec)

        self.body.addStretch(1)

    # ---- 电平测试 ----

    def _toggle_test(self) -> None:
        if self.picker.monitoring:
            self.stop_test()
        elif self.picker.start_monitor():
            self.btn_test.setText("停止测试")

    def stop_test(self) -> None:
        """离开这一页时也要调 —— 否则麦克风一直被占着。"""
        self.picker.stop_monitor()
        self.btn_test.setText("开始测试")

    def apply_palette(self, palette: Palette) -> None:
        self.picker.apply_palette(palette)

    # ---- 写回 ----

    def collect(self, cfg: Config) -> None:
        cfg.audio.device = self.picker.device()
        # 编号只是缓存,名字才是身份 —— 见 AudioConfig 的说明
        cfg.audio.device_name, cfg.audio.device_hostapi = self.picker.device_identity()
        cfg.audio.max_seconds = float(self.max_seconds.value())
