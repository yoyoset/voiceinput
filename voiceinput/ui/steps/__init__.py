"""首次运行向导的各个步骤。

拆开的判据是**"谁在改这个状态"**:下载线程归模型步、录音机归标定步、
热键控件归热键步。向导本身不认识任何一个具体控件。
"""

from .base import Step
from .done import DoneStep
from .hotkey import HotkeyStep
from .mic import CALIBRATION_PHRASE, MicStep
from .model import ModelStep
from .welcome import WelcomeStep

__all__ = [
    "Step",
    "WelcomeStep",
    "ModelStep",
    "MicStep",
    "HotkeyStep",
    "DoneStep",
    "CALIBRATION_PHRASE",
]
