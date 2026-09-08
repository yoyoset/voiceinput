"""SenseVoice-Small(sherpa-onnx)引擎。

开发机上的实测数据(Xeon E5-2698 v3,纯 CPU,8 线程):RTF 0.054,
18.4x 实时,5 秒的一句话 0.29 秒转完,模型加载约 3 秒。
**这是那台机器的数字,不是普遍结论** —— 界面上要显示性能,
用的是当前这台机器刚刚跑出来的值,不是这里写的。

模型必须用 **2024-07-17** 原版。2025-09-09 那个是粤语特化微调
(ASLP-lab/WSYue-ASR),中英日韩全线崩坏,详见 docs/engine-benchmark.md。
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from . import providers
from .base import EngineError, Transcription


class SenseVoiceEngine:
    name = "sensevoice"

    def __init__(self, model_dir: Path, provider: str = "cpu", num_threads: int = 8,
                 language: str = "auto", use_itn: bool = True) -> None:
        self._model_dir = Path(model_dir)
        # **在这里就把 provider 落到真的能用的那个上。**
        # 交给 sherpa-onnx 处理的话它会静默回退到 CPU,只往 stderr 打一行 ——
        # windowed 打包后没有 stderr,用户会一直以为在用显卡。
        self._provider, self.provider_note = providers.resolve(provider)
        self._num_threads = num_threads
        self._language = language
        self._use_itn = use_itn
        self._recognizer = None

    @property
    def is_loaded(self) -> bool:
        return self._recognizer is not None

    @property
    def model_dir(self) -> Path:
        return self._model_dir

    def load(self) -> None:
        if self._recognizer is not None:
            return

        model = self._model_dir / "model.int8.onnx"
        tokens = self._model_dir / "tokens.txt"
        missing = [p.name for p in (model, tokens) if not p.exists()]
        if missing:
            raise EngineError(
                f"模型文件缺失({', '.join(missing)})。\n目录: {self._model_dir}\n"
                "请在设置里重新下载模型。"
            )

        try:
            import sherpa_onnx
        except ImportError as e:  # pragma: no cover - 环境问题
            raise EngineError(f"sherpa-onnx 未安装: {e}") from e

        try:
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model),
                tokens=str(tokens),
                use_itn=self._use_itn,
                num_threads=self._num_threads,
                provider=self._provider,
                language=self._language,
            )
        except Exception as e:
            # sherpa-onnx 有时是 C++ 层硬退出,抓不到;能抓到的话给足上下文
            raise EngineError(
                f"模型加载失败: {e}\n"
                "若报 onnxruntime 版本不符,检查是否装了 sherpa-onnx-core"
                "(缺它会被 C:\\Windows\\System32\\onnxruntime.dll 顶包)。"
            ) from e

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> Transcription:
        if self._recognizer is None:
            raise EngineError("模型尚未加载")
        if audio.size == 0:
            return Transcription("", 0.0, 0.0)

        audio = np.asarray(audio, dtype=np.float32).ravel()
        t0 = time.perf_counter()
        try:
            stream = self._recognizer.create_stream()
            stream.accept_waveform(sample_rate, audio)
            self._recognizer.decode_stream(stream)
            text = stream.result.text
        except Exception as e:
            raise EngineError(f"识别失败: {e}") from e

        return Transcription(
            text=text,
            infer_seconds=time.perf_counter() - t0,
            audio_seconds=audio.size / sample_rate,
        )

    def unload(self) -> None:
        self._recognizer = None
