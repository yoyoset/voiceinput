from __future__ import annotations

from ..config import Config
from .base import Engine, EngineError, Transcription
from .sensevoice import SenseVoiceEngine

__all__ = ["Engine", "EngineError", "Transcription", "SenseVoiceEngine", "build_engine"]


def build_engine(cfg: Config) -> Engine:
    """按配置造引擎。目前只有 SenseVoice 一种实现。"""
    name = cfg.engine.name.lower()
    if name == "sensevoice":
        return SenseVoiceEngine(
            model_dir=cfg.model_path(),
            provider=cfg.engine.provider,
            num_threads=cfg.engine.num_threads,
            language=cfg.engine.language,
            use_itn=cfg.engine.use_itn,
        )
    raise EngineError(f"未知引擎: {cfg.engine.name}")
