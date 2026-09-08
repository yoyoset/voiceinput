"""录音时按 Esc 取消,不识别、不粘贴。

以前录音一旦开始就没有反悔的余地:说错了、改主意了,只能等热键松开,
让识别结果照常跑完再手动删掉粘出来的东西。这条路径给出一个明确的
"我不要这次了"的出口。
"""

from __future__ import annotations

import numpy as np
import pytest

from voiceinput.cancel_key import CancelKey
from voiceinput.session import RecordingSession


class FakeRecorder:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self):
        self.stopped = True
        return np.zeros(0, dtype=np.float32)


@pytest.fixture
def session(qapp):
    s = RecordingSession()
    yield s
    s.abort()


class TestSessionCancel:
    def test_没在录音时取消不生效(self, session):
        assert session.cancel() is False

    def test_取消会丢弃录音机(self, session):
        fake = FakeRecorder()
        session._recorder = fake
        assert session.cancel() is True
        assert fake.stopped
        assert session._recorder is None

    def test_取消之后回到就绪(self, session):
        session._recorder = FakeRecorder()
        session.cancel()
        assert session.is_idle

    def test_取消会发信号(self, session):
        session._recorder = FakeRecorder()
        seen = []
        session.cancelled.connect(lambda: seen.append(1))
        session.cancel()
        assert seen == [1]

    def test_取消不发失败信号(self, session):
        """**这不是失败** —— 用户是故意的,不该被当成"没录到音"那类错误。"""
        session._recorder = FakeRecorder()
        seen = []
        session.failed.connect(lambda msg: seen.append(msg))
        session.cancel()
        assert seen == []

    def test_正在等识别结果时取消不了(self, session):
        """那时候音频已经交出去了,`_recorder` 本来就是 None
        —— 没有"反悔"的窗口。"""
        session._busy = True
        assert session.cancel() is False


class TestCancelKey:
    def test_只在按下_esc_时发信号(self, qapp):
        key = CancelKey()
        seen = []
        key.pressed.connect(lambda: seen.append(1))

        from pynput import keyboard
        key._on_press(keyboard.Key.esc)
        key._on_press(keyboard.Key.space)
        key._on_press(keyboard.KeyCode.from_char("a"))

        assert seen == [1]

    def test_start_stop_是幂等的(self, qapp):
        """重复调用不该炸,也不该攒出好几个监听器。"""
        key = CancelKey()
        key.start()
        key.start()
        assert key._listener is not None
        key.stop()
        key.stop()
        assert key._listener is None
