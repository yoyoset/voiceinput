"""识别得出来吗。

**注意这里有两条不同的路径,都得验。**

`check_load` / `check_inference` 是**直接**调引擎,证明"引擎本身能用"。
但真实运行时 App 从不直接调它,而是把请求派到 worker 线程 ——
那条路径曾经完全是坏的(`Q_ARG` 传 Python 对象在 PySide6 里直接抛,
异常又被 Qt 吞掉),结果是**程序从来没加载过模型**,而自检九项全过,
因为自检走的是引擎、不是那条路。`check_dispatch` 补的就是这个盲区。
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..config import Config
from ..postprocess import clean
from .report import Report

DISPATCH_TIMEOUT_MS = 60_000


def model_file(cfg: Config) -> Path:
    return cfg.model_path() / "model.int8.onnx"


def check_model_file(report: Report, cfg: Config) -> bool:
    path = model_file(cfg)
    if not path.exists():
        report.failed(f"模型文件不存在: {path}")
        return False
    report.passed(f"模型文件存在 ({path.stat().st_size / 1024 / 1024:.0f} MB)")
    return True


def check_load(report: Report, cfg: Config):
    """加载模型 —— 打包后最容易坏的一步。返回引擎,失败返回 None。"""
    try:
        from ..asr import build_engine

        t0 = time.perf_counter()
        engine = build_engine(cfg)
        engine.load()
        report.passed(f"模型加载成功,耗时 {time.perf_counter() - t0:.2f}s")
        return engine
    except Exception as e:
        report.failed(f"模型加载: {e}")
        return None


def check_inference(report: Report, cfg: Config, engine) -> None:
    """真跑一次推理。

    用模型自带的示例音频,没有就用合成正弦波 —— 后者识别不出内容很正常,
    那种情况下这一步只验证推理通路不崩。
    """
    wav = cfg.model_path() / "test_wavs" / "zh.wav"
    try:
        if wav.exists():
            import soundfile as sf

            audio, sr = sf.read(wav, dtype="float32", always_2d=True)
            audio = audio[:, 0]
        else:
            sr = 16000
            t = np.linspace(0, 1.0, sr, dtype=np.float32)
            audio = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        result = engine.transcribe(audio, sr)
        report.passed(f"推理成功,{result.infer_seconds:.2f}s / "
                      f"{result.audio_seconds:.1f}s (RTF {result.rtf:.3f})")
        if wav.exists():
            report.detail(f"识别结果: {clean(result.text)}")
    except Exception as e:
        report.failed(f"推理: {e}")


def check_dispatch(report: Report, cfg: Config) -> None:
    """**App 是怎么用引擎的** —— 跨线程派发这条路径。"""
    try:
        from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Signal
        from PySide6.QtWidgets import QApplication

        from ..worker import EngineWorker

        QApplication.instance() or QApplication([])

        class _Driver(QObject):
            loadRequested = Signal(object)

        thread = QThread()
        worker = EngineWorker()
        worker.moveToThread(thread)
        driver = _Driver()
        driver.loadRequested.connect(worker.load)

        outcome: list = []
        worker.loaded.connect(lambda n: outcome.append(("ok", n)))
        worker.loadFailed.connect(lambda m, _ok: outcome.append(("fail", m)))

        thread.start()
        driver.loadRequested.emit(cfg)

        loop = QEventLoop()
        QTimer.singleShot(DISPATCH_TIMEOUT_MS, loop.quit)
        worker.loaded.connect(loop.quit)
        worker.loadFailed.connect(loop.quit)
        loop.exec()

        worker.unload()
        thread.quit()
        thread.wait(5000)

        if not outcome:
            report.failed("跨线程派发:请求根本没送到 worker —— "
                          "程序运行时会一直卡在「正在加载模型」且没有任何报错")
        elif outcome[0][0] == "fail":
            report.failed(f"跨线程派发到了,但加载失败:{outcome[0][1]}")
        else:
            report.passed("跨线程派发正常(App 就是这样用引擎的)")
    except Exception as e:
        report.failed(f"跨线程派发: {e}")


def check_provider(report: Report, cfg: Config) -> None:
    """配置里选的计算设备是不是真的能用。

    sherpa-onnx 的 CPU 版拿到 cuda 会**静默回退**,只往 stderr 打一行 ——
    windowed 打包后没有 stderr,于是界面写着 CUDA、实际跑在 CPU 上。
    """
    try:
        from ..asr import providers

        actual, note = providers.resolve(cfg.engine.provider)
        if note:
            report.failed(f"计算设备:配置写的是 {cfg.engine.provider},{note}")
        else:
            report.passed(f"计算设备 {actual} 可用"
                          f"(这个包带的后端:{'、'.join(providers.available())})")
    except Exception as e:
        report.failed(f"计算设备探测: {e}")
