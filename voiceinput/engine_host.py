"""识别引擎跑在哪个线程,以及"模型现在能不能用"。

拆出来的判据是**谁在改这些状态**:那个 worker 线程、worker 本身、
以及 `_ready` 这个"热键按下去会不会被拒"的开关。以前是 App 上的
`worker` / `worker_thread` / `_engine_ready`,被六处代码各自读写。

**App 从不直接调引擎**,一律经这里派到 worker 线程 ——
那条路径曾经完全是坏的而没有任何报错,见下面 `_loadRequested` 的说明。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .config import Config
from .worker import EngineWorker

log = logging.getLogger("voiceinput")


class Caveat:
    """"加载成功了,但是……"。

    `detail` 写在设置页的模型状态里,`banner` 是要弹出来的那句人话
    (空表示不弹)。
    """

    __slots__ = ("detail", "banner", "loud")

    def __init__(self, detail: str, banner: str, loud: bool) -> None:
        self.detail = detail
        self.banner = banner
        self.loud = loud


class EngineHost(QObject):
    """引擎线程的主人。一个 App 只需要一个。"""

    loading = Signal()
    """开始加载了。界面该显示"正在加载模型…"。"""

    ready = Signal(str, object)
    """加载成功。(模型名, Caveat | None)

    **加载成功不代表加载对了** —— 所以第二个参数是"保留意见"。
    """

    failed = Signal(str, bool)
    """(message, 旧引擎是否还活着)

    第二个参数不能省:新模型没加载起来但旧的还在时,不该把热键禁掉 ——
    用户只是配置填错了,不该连原来能用的都没了。
    """

    transcribed = Signal(object, str)      # Transcription, action
    transcribeFailed = Signal(str, str)    # message, action

    # 派往 worker 线程的请求。
    #
    # **必须用信号,不能用 QMetaObject.invokeMethod + Q_ARG(object, ...)** ——
    # PySide6 里那样传 Python 对象会直接抛:
    #     RuntimeError: qArgDataFromPyType: Unable to find a QMetaType for "object"
    # 而它跑在 QTimer 回调里,异常被 Qt 打到 stderr 后吞掉;
    # windowed 打包后没有 stderr,于是**完全静默** —— 程序从来没加载过模型,
    # 界面上却只显示"正在加载模型…",没有任何报错。
    _loadRequested = Signal(object)                    # Config
    _transcribeRequested = Signal(object, int, str)    # audio, sample_rate, action

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ready = False
        self._loaded_fingerprint: tuple | None = None
        self._thread = QThread()
        self._worker = EngineWorker()
        self._worker.moveToThread(self._thread)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.loadFailed.connect(self._on_failed)
        self._worker.transcribed.connect(self.transcribed.emit)
        self._worker.transcribeFailed.connect(self.transcribeFailed.emit)
        # 跨线程派发走信号 —— worker 在别的线程,Qt 会自动用队列连接
        self._loadRequested.connect(self._worker.load)
        self._transcribeRequested.connect(self._worker.transcribe)

    @property
    def is_ready(self) -> bool:
        """模型加载好了吗。没好就该拒绝录音,并且说清楚为什么。"""
        return self._ready

    def start(self) -> None:
        self._thread.start()

    # ---- 请求 ----

    def apply(self, cfg: Config) -> None:
        """配置变了。**只有影响引擎的那几项变了才重新加载。**

        由这里自己比对,而不是让调用方列一串 `cfg.engine.X != old.engine.X` ——
        那样每加一个引擎配置项,调用方那边的 if 就得跟着改一次,
        而漏改的表现是"改了设置没生效,并且不报错"。
        """
        if self._fingerprint(cfg) == self._loaded_fingerprint:
            return
        self.load(cfg)

    @staticmethod
    def _fingerprint(cfg: Config) -> tuple:
        """决定"要不要重新加载"的那几项。

        `language` 不在里面:实测 auto 与 zh 输出逐字相同,而重载要 3 秒。
        model_dir 用解析后的绝对路径 —— 相对写法改了但指向同一个目录时
        不该白重载一次。
        """
        return (str(cfg.model_path()), cfg.engine.provider,
                cfg.engine.num_threads, cfg.engine.use_itn)

    def load(self, cfg: Config) -> None:
        """无条件(重新)加载模型。设置页那个「重新加载模型」按钮走这条。

        **不在这里把 `_ready` 置 False。** worker 只在新引擎加载成功之后
        才换掉旧的,所以重载期间旧引擎仍然可用;提前置 False 会让
        "改个线程数"这段时间里按热键直接被拒。真正决定它的是加载结果。
        """
        self._cfg = cfg
        self._loaded_fingerprint = self._fingerprint(cfg)
        log.info("请求加载模型: %s", cfg.model_path())
        self.loading.emit()
        self._loadRequested.emit(cfg)

    def transcribe(self, audio, sample_rate: int, action: str) -> None:
        self._transcribeRequested.emit(audio, sample_rate, action)

    def stop(self) -> None:
        self._thread.quit()
        self._thread.wait(3000)

    # ---- 结果 ----

    @Slot(str)
    def _on_loaded(self, name: str) -> None:
        self._ready = True
        log.info("模型已加载: %s", name)
        self.ready.emit(name, self._caveat())

    @Slot(str, bool)
    def _on_failed(self, message: str, still_usable: bool) -> None:
        self._ready = still_usable
        self.failed.emit(message, still_usable)

    def _caveat(self) -> Caveat | None:
        """加载成功之后仍然要说的话。没有就返回 None。

        两件事都属于"跑起来了,但不是你以为的那样",而且都**不会报错** ——
        不主动说的话,用户只会觉得"这工具就这样"。
        """
        from . import download as dl
        from .asr import providers

        status = dl.check(self._cfg.model_path())
        if status.warning:
            # 粤语特化版同样是两百多 MB、同样能跑,只是中英日韩全面变差。
            # 这个必须弹出来,它直接毁掉识别质量。
            return Caveat(status.warning, "模型版本不对,识别质量会明显下降", loud=True)

        _, note = providers.resolve(self._cfg.engine.provider)
        if note:
            # 选了 CUDA 而这个包只带 CPU 后端 —— sherpa-onnx 会静默回退。
            # 不影响能不能用,所以不弹窗,写在设置页上就够了。
            return Caveat(note, "", loud=False)
        return None
