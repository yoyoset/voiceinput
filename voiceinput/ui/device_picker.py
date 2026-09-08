"""麦克风选择 + 实时电平。设置页和向导共用。

**抽出来的理由不是"减少行数",是这段逻辑在两处已经漂移了**:
同样一句提示,设置页写的是"— 太低,这个设备可能不是话筒",
向导写的是"—— 太低,可能不是话筒"。同一个概念两套措辞,
改了一处另一处继续过时。

而这段逻辑恰恰是最要紧的一环:系统默认的输入设备经常不是话筒 ——
光看名字分不出来,只能看电平。判断"这到底是不是你的话筒"的标准
必须只有一份,提示文案也是。
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import audio as audio_mod
from .theme import Palette
from .widgets import ComboBox, LevelBar, labeled

POLL_MS = 60

DEFAULT_HINT = "对着麦克风说话,绿条要明显越过竖线"

_BASE_HINT = (
    "竖线左边是静音区,说话时绿条要明显越过它才算选对。\n"
    "**别按设备名猜** —— 名字好听的未必是话筒,唯一可靠的办法是说一句话看电平。"
)


def device_hint() -> str:
    """选设备那一栏下面的说明。**内容由这台机器真实枚举到的设备决定。**

    以前设置页和向导各写死了一段开发机的情况("所有设备都是 RØDE Connect
    的虚拟设备")。那对别人既不准也帮不上忙,还会让人以为程序认错了硬件。
    """
    try:
        suspects = audio_mod.suspicious_devices()
    except Exception:
        return _BASE_HINT          # 枚举失败不该连提示都没有
    if not suspects:
        return _BASE_HINT
    # 同一个设备在 MME 和 WASAPI 下各出现一次,名字一样 —— 按名字去重,
    # 否则提示里会把同一个名字念两遍
    unique = list(dict.fromkeys(d.name for d in suspects))
    names = "、".join(f"「{n}」" for n in unique[:3])
    return (
        f"注意:{names} 这类名字通常是**系统声音回环**而不是话筒 —— "
        "选中它照样能录,录到的是电脑正在放的声音。\n" + _BASE_HINT
    )


class DevicePicker(QWidget):
    """下拉选设备 + 电平条 + 一行结论。

    监听的启停交给调用方:设置页是点按钮才测,向导是进到那一步自动测。
    但**监听本身、电平换算、结论文案只有这一份**。
    """

    deviceChanged = Signal(object)   # 设备编号,None 表示系统默认

    def __init__(self, palette: Palette, device: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._monitor: audio_mod.LevelMonitor | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self.combo = ComboBox()
        layout.addLayout(labeled("麦克风", self.combo))

        self.bar = LevelBar()
        layout.addLayout(labeled("电平", self.bar))

        self.hint = QLabel(DEFAULT_HINT)
        self.hint.setProperty("role", "hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

        self.apply_palette(palette)
        self.reload_devices(device)
        self.combo.currentIndexChanged.connect(self._on_changed)

    # ---- 对外 ----

    def device(self) -> int | None:
        return self.combo.currentData()

    def device_identity(self) -> tuple[str, str]:
        """选中设备的 (名字, hostapi)。

        **编号不能当身份存**:PortAudio 的 index 是枚举序号,插拔设备就会重排。
        存下来的必须是这一对。系统默认返回 ("", "")。
        """
        idx = self.device()
        if idx is None:
            return "", ""
        for d in audio_mod.list_devices():
            if d.index == idx:
                return d.name, d.hostapi
        return "", ""

    def reload_devices(self, select: int | None = ...) -> None:
        """重新枚举设备。select 省略时保持当前选择。"""
        keep = self.device() if select is ... else select
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("系统默认(不推荐)", None)
        try:
            for d in audio_mod.list_devices():
                self.combo.addItem(d.label, d.index)
        except Exception as e:
            self.combo.addItem(f"枚举设备失败:{e}", None)
        idx = self.combo.findData(keep)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo.blockSignals(False)

    @property
    def monitoring(self) -> bool:
        return self._monitor is not None

    def start_monitor(self) -> bool:
        """开始测电平。打不开麦克风时把原因显示出来并返回 False。"""
        if self._monitor is not None:
            return True
        try:
            self._monitor = audio_mod.LevelMonitor(device=self.device())
            self._monitor.start()
        except audio_mod.RecordingError as e:
            self._monitor = None
            self._set_hint(str(e), ok=False)
            return False
        self._set_hint(DEFAULT_HINT, ok=True)
        self._timer.start(POLL_MS)
        return True

    def stop_monitor(self) -> None:
        """停止测电平。**离开界面时必须调**,否则麦克风一直被占着。"""
        self._timer.stop()
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
        self.bar.set_level(float("-inf"))
        self._set_hint(DEFAULT_HINT, ok=True)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.bar.set_colors(
            palette.accent, palette.danger, palette.surface_alt, palette.text_dim
        )

    # ---- 内部 ----

    def _on_changed(self) -> None:
        # 换了设备就得重新开监听 —— 旧的还连在上一个设备上
        was_monitoring = self.monitoring
        self.stop_monitor()
        if was_monitoring:
            self.start_monitor()
        self.deviceChanged.emit(self.device())

    def _poll(self) -> None:
        if self._monitor is None:
            return
        level = self._monitor.level_dbfs
        self.bar.set_level(level)
        if level == float("-inf"):
            self._set_hint("没有信号", ok=False)
        elif self.bar.is_silent:
            # 这句是整个工具最容易被忽略的提示:有电平不代表是话筒,
            # 系统声音回环同样有电平。
            self._set_hint(f"{level:.0f} dBFS —— 太低,这个设备可能不是话筒", ok=False)
        else:
            self._set_hint(f"{level:.0f} dBFS —— 有信号", ok=True)

    def _set_hint(self, text: str, ok: bool) -> None:
        self.hint.setText(text)
        self.hint.setProperty("role", "hint" if ok else "danger")
        self.hint.style().unpolish(self.hint)
        self.hint.style().polish(self.hint)
