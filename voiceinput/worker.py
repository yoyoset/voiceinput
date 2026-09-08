"""模型加载与推理的工作线程。

模型加载要 3 秒、推理要零点几秒——都不能放在 UI 线程,否则界面会卡住。
引擎对象只在这一个线程里创建和使用,不跨线程共享,省掉一层同步。
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from .asr import Engine, EngineError, Transcription
from .config import Config


class EngineWorker(QObject):
    """住在工作线程里的引擎持有者。所有槽都在那个线程上执行。"""

    loaded = Signal(str)                 # 成功,附带模型描述
    # (错误消息, 是否仍有可用引擎)。第二个参数很关键:加载失败时旧引擎
    # 可能还活着,上层不该因此把热键禁掉。
    loadFailed = Signal(str, bool)
    transcribed = Signal(object, str)    # Transcription, action
    transcribeFailed = Signal(str, str)  # message, action

    def __init__(self) -> None:
        super().__init__()
        self._engine: Engine | None = None

    @Slot(object)
    def load(self, cfg: Config) -> None:
        """加载模型。**新的加载成功之前,绝不动旧的。**

        原来第一行就是 `self._engine = None`,然后才去加载。于是配置填错
        (比如模型目录敲错一个字母)会让本来能用的引擎直接消失 ——
        从"改错一个设置"升级成"整个程序不能用",而用户只是想调个线程数。

        代价是切换的瞬间内存里会同时存在两份模型(约 500MB)。
        比起"弄丢一个能用的引擎",这个代价可以接受,而且是瞬时的。
        """
        from .asr import build_engine

        try:
            engine = build_engine(cfg)
            engine.load()
        except EngineError as e:
            self.loadFailed.emit(str(e), self._engine is not None)
            return
        except Exception as e:  # 兜底:引擎实现里漏掉的异常不能让线程静默死掉
            self.loadFailed.emit(f"模型加载失败: {e}", self._engine is not None)
            return

        old, self._engine = self._engine, engine
        if old is not None:
            try:
                old.unload()   # 换成功了才放掉旧的,不然内存里会一直留着
            except Exception:
                pass           # 释放失败不该让这次成功的加载算作失败
        self.loaded.emit(cfg.model_path().name)

    @Slot(object, int, str)
    def transcribe(self, audio: np.ndarray, sample_rate: int, action: str) -> None:
        if self._engine is None:
            self.transcribeFailed.emit("模型尚未加载完成", action)
            return
        try:
            result: Transcription = self._engine.transcribe(audio, sample_rate)
        except EngineError as e:
            self.transcribeFailed.emit(str(e), action)
            return
        except Exception as e:
            self.transcribeFailed.emit(f"识别失败: {e}", action)
            return
        self.transcribed.emit(result, action)

    @Slot()
    def unload(self) -> None:
        if self._engine is not None:
            self._engine.unload()
            self._engine = None
