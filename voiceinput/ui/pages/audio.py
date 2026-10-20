"""「音频」页:选设备、看电平、录音上限。"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton

from ...audio import resolve_device
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
        #
        # **预选必须按名字解析,不能直接拿 cfg.audio.device。** 编号只是缓存:
        # 2026-10-04 实际出过 —— 话筒不在线时 1 号变成了系统回环,下拉框照着
        # 编号选中它,随后改了别的设置,collect() 就把回环存成了"用户选的话筒";
        # 话筒回来后 1 号又是它,界面显示话筒、实际按名字录的是回环,全是静音。
        index, self._absent = self._saved_device(cfg)
        self.picker = DevicePicker(palette, index)
        self.picker.deviceChanged.connect(self._on_picked)
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

    @staticmethod
    def _saved_device(cfg: Config) -> tuple[int | None, bool]:
        """(现在该预选的编号, 存下来的那个设备是不是不在线)。"""
        a = cfg.audio
        try:
            index, _ = resolve_device(a.device, a.device_name, a.device_hostapi)
        except Exception:           # 枚举失败时下拉框自己会把原因显示出来
            return None, bool(a.device_name)
        return index, bool(a.device_name) and index is None

    def _on_picked(self, *_) -> None:
        self._absent = False        # 用户亲手选过了,以他选的为准
        self.emit_changed()

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
        # 存的话筒只是暂时不在线、用户也没动过下拉框:别拿下拉框里的替身
        # 把它的名字盖掉,否则话筒插回来也认不回去了。
        if not self._absent:
            cfg.audio.device = self.picker.device()
            # 编号只是缓存,名字才是身份 —— 见 AudioConfig 的说明
            name, hostapi = self.picker.device_identity()
            cfg.audio.device_name, cfg.audio.device_hostapi = name, hostapi
        cfg.audio.max_seconds = float(self.max_seconds.value())
