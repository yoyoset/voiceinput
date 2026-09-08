"""EngineHost 的三个信号该往主窗口/悬浮条/状态栏上写什么字。

这段以前在 App 上,靠集成测试间接兜底。拆出 `EngineStatus` 之后专门
钉住,免得下次改动只被集成测试隐约覆盖到,出了偏差也看不清是哪一句。
"""

from __future__ import annotations

import pytest

from voiceinput.engine_host import Caveat
from voiceinput.engine_status import EngineStatus


class FakeWindow:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, str]] = []

    def set_model_status(self, ok: bool, message: str) -> None:
        self.calls.append((ok, message))


class FakeOverlay:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, int]] = []
        self.errors: list[tuple[str, int]] = []

    def show_warning(self, message: str, duration_ms: int) -> None:
        self.warnings.append((message, duration_ms))

    def show_error(self, message: str, duration_ms: int) -> None:
        self.errors.append((message, duration_ms))


class FakeStatus:
    def __init__(self) -> None:
        self.shown: list[tuple[str, str, str]] = []
        self.refreshed = 0

    def show(self, state: str, text: str, detail: str = "") -> None:
        self.shown.append((state, text, detail))

    def refresh(self) -> None:
        self.refreshed += 1


@pytest.fixture
def parts(qapp):
    return FakeWindow(), FakeOverlay(), FakeStatus()


def make(parts, idle: bool = True) -> EngineStatus:
    window, overlay, status = parts
    return EngineStatus(window, overlay, status, is_idle=lambda: idle)


class TestLoading:
    def test_闲着时把状态栏改成加载中(self, parts):
        window, _, status = parts
        make(parts, idle=True).loading()
        assert status.shown == [("loading", "正在加载模型…", "")]
        assert window.calls == [(True, "正在加载…")]

    def test_录音中不打断状态栏(self, parts):
        """录音仍在继续,盖成"正在加载模型…"会让用户以为录音断了。"""
        window, _, status = parts
        make(parts, idle=False).loading()
        assert status.shown == []
        assert window.calls == [(True, "正在加载…")]   # 设置页的状态不受影响


class TestReady:
    def test_没有保留意见就是纯粹的成功(self, parts):
        window, overlay, status = parts
        make(parts).ready("sensevoice", None)
        assert status.refreshed == 1
        assert window.calls == [(True, "已加载:sensevoice")]
        assert overlay.warnings == []

    def test_有保留意见时设置页要说清楚(self, parts):
        window, _, _ = parts
        caveat = Caveat(detail="CPU 回退", banner="", loud=False)
        make(parts).ready("sensevoice", caveat)
        assert window.calls == [(False, "已加载:sensevoice\nCPU 回退")]

    def test_loud_的保留意见要弹悬浮条(self, parts):
        _, overlay, _ = parts
        caveat = Caveat(detail="CPU 回退", banner="选了 CUDA 但在用 CPU", loud=True)
        make(parts).ready("sensevoice", caveat)
        assert overlay.warnings == [("选了 CUDA 但在用 CPU", 6000)]

    def test_不_loud_的保留意见不弹悬浮条(self, parts):
        """只值得在设置页写一句,不到要弹窗打扰的程度。"""
        _, overlay, _ = parts
        caveat = Caveat(detail="次要差异", banner="", loud=False)
        make(parts).ready("sensevoice", caveat)
        assert overlay.warnings == []


class TestFailed:
    def test_旧模型还能用就只是警告(self, parts):
        window, overlay, status = parts
        make(parts).failed("配置里的路径不对", still_usable=True)
        assert window.calls == [(False, "配置里的路径不对")]
        assert status.refreshed == 1
        assert overlay.warnings == [("新模型没加载成功,仍在用之前的模型", 5000)]
        assert overlay.errors == []

    def test_没有旧模型可用就是真的失败(self, parts):
        """**不能把热键禁掉的例外只适用于 still_usable。**
        这里没有旧模型兜底,必须明确说"模型未加载"。"""
        window, overlay, status = parts
        make(parts).failed("模型文件损坏\n详细堆栈略", still_usable=False)
        assert window.calls == [(False, "模型文件损坏\n详细堆栈略")]
        assert status.shown == [("error", "模型未加载", "模型文件损坏")]
        assert overlay.errors == [("模型加载失败,请在设置里检查", 5000)]
        assert overlay.warnings == []
