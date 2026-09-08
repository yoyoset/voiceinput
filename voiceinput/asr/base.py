"""ASR 引擎接口。

留抽象层的理由不是"以后可能要换",而是引擎选型**现在就还没定**:
SenseVoice 快得多但会错词,faster-whisper 更准但在开发机上纯 CPU 只有
0.2x 实时(那台机器的显卡被别的程序常年占满,GPU 路线没法评估)。
要等真人录音的 CER 才能拍板。接口把这个未决的选择挡在应用逻辑之外。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


class EngineError(RuntimeError):
    """模型加载失败、推理失败。必须让用户看见。"""


@dataclass
class Transcription:
    text: str
    """原始识别文本,未经后处理。"""
    infer_seconds: float
    audio_seconds: float

    @property
    def rtf(self) -> float:
        """实时率。越小越快,1.0 表示刚好实时。"""
        return self.infer_seconds / self.audio_seconds if self.audio_seconds else 0.0


@runtime_checkable
class Engine(Protocol):
    name: str

    def load(self) -> None:
        """加载模型。耗时操作,必须在后台线程调用。

        实现要保证可重复调用:已加载时直接返回,不重复加载。
        """
        ...

    @property
    def is_loaded(self) -> bool: ...

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> Transcription:
        """转写单声道 float32 音频。未加载时应抛 EngineError。"""
        ...

    def unload(self) -> None: ...
