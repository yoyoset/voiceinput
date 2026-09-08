"""向导第二步:把语音识别模型准备好。

这一步独有的状态是**那个下载线程**。它必须在向导关闭时被叫停,
否则线程会带着一个已销毁的窗口继续跑。
"""

from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton

from ... import download as dl
from ...config import Config, app_dir
from ..widgets import Card, hint, restyle
from .base import Step


class ModelStep(Step):
    def __init__(self, cfg: Config, backend, parent=None) -> None:
        super().__init__("语音识别模型", parent)
        self._cfg = cfg
        self._backend = backend
        self._thread: QThread | None = None
        self._worker: dl.DownloadWorker | None = None

        card = Card()
        self.status = QLabel("检查中…")
        self.status.setWordWrap(True)
        card.add(self.status)

        self.path_label = QLabel("")
        self.path_label.setProperty("role", "mono")
        self.path_label.setWordWrap(True)
        card.add(self.path_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        card.add(self.bar)

        self.dl_hint = QLabel("")
        self.dl_hint.setProperty("role", "hint")
        card.add(self.dl_hint)

        btns = QHBoxLayout()
        self.btn_download = QPushButton("下载模型")
        self.btn_download.setProperty("role", "primary")
        self.btn_download.clicked.connect(self.start_download)
        self.btn_recheck = QPushButton("重新检查")
        self.btn_recheck.clicked.connect(self.refresh)
        btns.addWidget(self.btn_download)
        btns.addWidget(self.btn_recheck)
        btns.addStretch(1)
        card.add_layout(btns)
        self.body.addWidget(card)

        self.body.addWidget(hint(
            "用的是 SenseVoice-Small 2024-07-17 原版。\n"
            "纯 CPU 就能跑,不需要显卡。具体在你这台机器上有多快,"
            "下一步标定时会实测出来。"
        ))
        self.body.addStretch(1)

    def on_enter(self) -> None:
        self.refresh()

    # ---- 状态 ----

    def refresh(self) -> None:
        status = dl.check(self._cfg.model_path())
        self.path_label.setText(str(status.path))
        if status.present and status.warning:
            # 模型能加载,但是错的那一版 —— 不拦着用,但必须说清楚,
            # 否则用户只会觉得"这工具识别不准"。
            self.status.setText(f"模型{status.message},但{status.warning}")
            self.status.setProperty("role", "danger")
        elif status.present:
            self.status.setText(f"模型{status.message}")
            self.status.setProperty("role", "hint")
            self.btn_download.setText("重新下载")
            self.btn_download.setProperty("role", "")
        else:
            self.status.setText(f"还没有模型:{status.message}")
            self.status.setProperty("role", "danger")
            self.btn_download.setText("下载模型")
            self.btn_download.setProperty("role", "primary")
        restyle(self.status)
        restyle(self.btn_download)

    def summary_rows(self) -> list[tuple[str, str]]:
        status = dl.check(self._cfg.model_path())
        return [("模型", status.message if status.present else "尚未就绪")]

    # ---- 下载 ----

    def start_download(self) -> None:
        if self._thread is not None:
            return
        self._set_busy(True)
        self.bar.setVisible(True)
        self.bar.setValue(0)

        self._thread = QThread()
        self._worker = dl.DownloadWorker(self._cfg.model_path().parent)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _set_busy(self, busy: bool) -> None:
        self.btn_download.setEnabled(not busy)
        self.btn_recheck.setEnabled(not busy)
        self.busyChanged.emit(busy)

    def _on_progress(self, pct: int, message: str) -> None:
        self.bar.setValue(pct)
        self.dl_hint.setText(message)

    def _end(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None
        self._set_busy(False)

    def _on_finished(self, path: str) -> None:
        self._end()
        self.bar.setVisible(False)
        self.dl_hint.setText("")
        # 下载目录可能和配置里写的不一致(比如用户改过),以实际落地的为准
        p = dl.Path(path)
        try:
            self._cfg.engine.model_dir = str(p.relative_to(app_dir()))
        except ValueError:
            self._cfg.engine.model_dir = str(p)
        self.refresh()
        self._backend.reload_engine()

    def _on_failed(self, message: str) -> None:
        self._end()
        self.bar.setVisible(False)
        self.dl_hint.setText(message)
        self.dl_hint.setProperty("role", "danger")
        restyle(self.dl_hint)

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._end()
