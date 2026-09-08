"""现在实际用的是哪个输入设备。

拆出来的判据是**谁在改这个状态**:那个解析出来的设备编号,和"解析过程中
有没有话要对用户说"。以前是 App 上的 `_resolved_device` / `_device_note`,
而"配置里的设备有没有变"还写在 App 的配置分发里 —— 等于让 App 替这一摊
记着它自己的旧值。

**配置里存的编号只是缓存,名字才是身份。** PortAudio 的 index 是枚举序号,
插拔任何一个音频设备都会重排;认编号会在某天悄悄录到别的设备上,
而录错设备的表现是"按了热键没反应"或"只录到静音" —— 用户根本不会想到
是编号漂了。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from .audio import resolve_device
from .config import Config

log = logging.getLogger("voiceinput")


class Microphone(QObject):
    """把配置里的麦克风解析成当前这一刻的设备编号。"""

    noteChanged = Signal(str)
    """解析结果和用户以为的不一样 —— **悄悄换设备是这个项目最忌讳的事**。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._index: int | None = None
        self._note = ""
        self._wanted: tuple[int | None, str, str] | None = None

    @property
    def index(self) -> int | None:
        """录音时该用的设备编号。None = 系统默认。"""
        return self._index

    @property
    def note(self) -> str:
        """上次解析留下的话。没有就是空串。"""
        return self._note

    def apply(self, cfg: Config) -> None:
        """按配置重新解析。**和上次要的一样就什么都不做。**

        由这里自己比对,而不是让调用方替我们记着旧值。
        """
        wanted = (cfg.audio.device, cfg.audio.device_name, cfg.audio.device_hostapi)
        if wanted == self._wanted:
            return
        self._wanted = wanted

        try:
            index, note = resolve_device(*wanted)
        except Exception as e:          # 枚举设备失败不该拦住启动
            self._index, self._note = cfg.audio.device, ""
            log.warning("解析音频设备失败: %s", e)
            return

        self._index, self._note = index, note
        if note:
            log.warning("音频设备: %s", note)
            self.noteChanged.emit(note)
        elif index != cfg.audio.device and cfg.audio.device_name:
            log.info("设备编号从 %s 漂到 %s(按名字找回)", cfg.audio.device, index)
