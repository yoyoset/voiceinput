"""向导正在等一个标定结果 —— 这件事的生命周期。

**要守的不变量:向导一销毁,等待中的回调就必须丢掉。**

那个回调指向向导里的控件,对着已销毁的 Qt 对象调会抛 RuntimeError。
而它是在识别线程回来时才被调用的 —— 也就是说崩溃发生在用户关掉向导
之后好几秒,现场早就没了。
"""

import pytest

from voiceinput.wizard_host import WizardHost


class FakeEngine:
    """替身引擎 —— 真的加载模型要 3 秒,而这里测的是回调的生命周期。"""

    def __init__(self, ready: bool = True) -> None:
        self.is_ready = ready
        self.loads: list = []
        self.transcribes: list = []

    def load(self, cfg) -> None:
        self.loads.append(cfg)

    def transcribe(self, audio, sample_rate, action) -> None:
        self.transcribes.append((audio, sample_rate, action))


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def host(qapp, engine):
    return WizardHost(engine)


class TestPendingCallback:
    def test_nothing_waiting_by_default(self, host):
        assert not host.is_waiting

    def test_deliver_without_a_waiter_reports_false(self, host):
        """没人在等要说清楚,调用方才知道该走普通的失败路径。"""
        assert host.deliver("文字", None) is False

    def test_deliver_reaches_the_waiter(self, host):
        got = []
        host.expect(lambda text, err: got.append((text, err)))
        assert host.deliver("把这个 function 改成 async", None) is True
        assert got == [("把这个 function 改成 async", None)]

    def test_error_reaches_the_waiter(self, host):
        got = []
        host.expect(lambda text, err: got.append((text, err)))
        host.deliver(None, "识别超时")
        assert got == [(None, "识别超时")]

    def test_callback_is_used_once(self, host):
        """**交完就清掉。** 否则下一次普通听写的结果会被塞进一个
        早就不该收东西的地方。"""
        calls = []
        host.expect(lambda text, err: calls.append(text))
        host.deliver("第一次", None)
        assert host.deliver("第二次", None) is False
        assert calls == ["第一次"]

    def test_expect_replaces_the_previous_waiter(self, host):
        calls = []
        host.expect(lambda text, err: calls.append("旧"))
        host.expect(lambda text, err: calls.append("新"))
        host.deliver("x", None)
        assert calls == ["新"]


class TestDeadWidgetIsSurvivable:
    def test_runtime_error_from_a_destroyed_widget_is_swallowed(self, host):
        """向导控件已销毁而 closed 信号还没到的窄窗口。

        这个异常不能冒到 Qt 的信号处理里去 —— 那会变成一次
        无人接管的崩溃,而且崩在识别线程回来的那一刻,离用户
        关掉向导已经过去好几秒。
        """
        def dead(text, err):
            raise RuntimeError("Internal C++ object already deleted.")

        host.expect(dead)
        assert host.deliver("文字", None) is True     # 不抛
        assert not host.is_waiting

    def test_other_exceptions_are_not_swallowed(self, host):
        """只吞"控件没了"这一种。别的异常吞掉就等于制造静默失败。"""
        def boom(text, err):
            raise ValueError("真的有 bug")

        host.expect(boom)
        with pytest.raises(ValueError):
            host.deliver("文字", None)


class TestDialogLifecycle:
    def test_closing_drops_the_pending_callback(self, host, qapp):
        """**这条是这个类存在的理由。**"""
        calls = []
        host.expect(lambda text, err: calls.append(text))
        host._on_closed()
        assert not host.is_waiting
        assert host.deliver("迟到的结果", None) is False
        assert calls == []

    def test_closed_signal_is_emitted(self, host):
        seen = []
        host.closed.connect(lambda: seen.append(True))
        host._on_closed()
        assert seen == [True]

    def test_not_open_by_default(self, host):
        assert not host.is_open


class TestBackendRole:
    """向导要的后端就是 WizardHost 自己。

    这三个方法原来挂在 App 上,只为向导存在 —— App 转发一遍,
    而"谁在等标定结果"本来就归 WizardHost 管。
    """

    def test_reports_engine_readiness(self, host, engine):
        assert host.is_engine_ready()
        engine.is_ready = False
        assert not host.is_engine_ready()

    def test_transcribe_goes_to_the_engine_as_a_wizard_job(self, host, engine):
        """标记成 "wizard" 才不会被当成普通听写去粘贴、写历史。"""
        host.transcribe_async(b"audio", 48000, lambda t, e: None)
        assert engine.transcribes == [(b"audio", 48000, "wizard")]

    def test_transcribe_registers_the_waiter(self, host):
        host.transcribe_async(b"audio", 48000, lambda t, e: None)
        assert host.is_waiting

    def test_transcribe_without_a_model_answers_immediately(self, host, engine):
        """**不能默默什么都不做。** 标定那一步会一直显示"识别中…"。"""
        engine.is_ready = False
        got = []
        host.transcribe_async(b"audio", 48000, lambda t, e: got.append((t, e)))
        assert got == [(None, "模型尚未加载完成")]
        assert engine.transcribes == []
        assert not host.is_waiting

    def test_reload_forces_a_load_not_an_apply(self, host, engine, qapp):
        """**必须是 load 而不是 apply。**

        向导刚下载完模型,而模型目录这个字符串可能一点没变(原来就指着
        这个路径,只是里面没东西)—— `apply` 会认为"没变"而跳过,
        表现是下载完成了却一直"模型未加载"。
        """
        from voiceinput.config import Config

        host._cfg = Config()
        host.reload_engine()
        assert len(engine.loads) == 1

    def test_reload_before_opening_is_a_noop(self, host, engine):
        """还没打开过向导就没有 cfg 可用,不该崩。"""
        host.reload_engine()
        assert engine.loads == []


class TestOpenWiresItselfIn:
    """`open()` 把自己当后端传给向导 —— 这一步接错了不会报错,
    只会表现为"标定按住说话没反应"。"""

    def make(self, host, tmp_path, monkeypatch):
        from voiceinput.config import Config
        from voiceinput.ui import theme

        cfg = Config()
        cfg.engine.model_dir = str(tmp_path)      # 别去碰真实模型目录
        host.open(cfg, theme.DARK)
        return cfg

    def test_dialog_gets_this_host_as_backend(self, host, tmp_path, monkeypatch):
        self.make(host, tmp_path, monkeypatch)
        try:
            assert host.is_open
            assert host._dialog.mic._backend is host
            assert host._dialog.model._backend is host
        finally:
            host._dialog.close()

    def test_second_open_does_not_make_a_second_dialog(self, host, tmp_path, monkeypatch):
        cfg = self.make(host, tmp_path, monkeypatch)
        first = host._dialog
        try:
            host.open(cfg, first._palette)
            assert host._dialog is first
        finally:
            first.close()

    def test_open_remembers_the_config_for_reload(self, host, engine, tmp_path,
                                                  monkeypatch):
        """模型步下载完会调 reload_engine(),那时得知道用哪份配置。"""
        cfg = self.make(host, tmp_path, monkeypatch)
        try:
            host.reload_engine()
            assert engine.loads == [cfg]
        finally:
            host._dialog.close()
