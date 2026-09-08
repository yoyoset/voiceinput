"""「加载成功了,但是……」这一类结论。

模型加载成功**不代表加载对了**,而且这两种情况都**不会报错**:

- 装的是粤语特化版:同样两百多 MB、同样能跑,只是中英日韩全面变差
- 选了 CUDA 而这个包只带 CPU 后端:sherpa-onnx 静默回退

不主动说的话,用户只会觉得"这工具就这样"。所以加载成功这条路上
必须能带一句保留意见回来。
"""

import pytest

from voiceinput.config import Config
from voiceinput.engine_host import Caveat, EngineHost


class FakeStatus:
    def __init__(self, warning=""):
        self.warning = warning


@pytest.fixture
def host(qapp):
    h = EngineHost()
    h._cfg = Config()
    yield h


def fake_checks(monkeypatch, *, model_warning="", provider_note=""):
    from voiceinput import download as dl
    from voiceinput.asr import providers

    monkeypatch.setattr(dl, "check", lambda path: FakeStatus(model_warning))
    monkeypatch.setattr(providers, "resolve", lambda p: ("cpu", provider_note))


class TestCaveat:
    def test_clean_load_has_nothing_to_add(self, host, monkeypatch):
        fake_checks(monkeypatch)
        assert host._caveat() is None

    def test_wrong_model_variant_is_loud(self, host, monkeypatch):
        """**这个必须弹出来** —— 它直接毁掉识别质量,而且不会报错。"""
        fake_checks(monkeypatch, model_warning="这是粤语特化版")
        caveat = host._caveat()
        assert caveat.loud and caveat.banner
        assert "粤语" in caveat.detail

    def test_provider_fallback_is_quiet(self, host, monkeypatch):
        """回退到 CPU 不影响能不能用,写在设置页上就够了,不该弹窗打断人。"""
        fake_checks(monkeypatch, provider_note="这个版本不支持 CUDA,已改用 CPU")
        caveat = host._caveat()
        assert not caveat.loud
        assert "CUDA" in caveat.detail

    def test_model_variant_wins_over_provider(self, host, monkeypatch):
        """两个都成立时先说模型 —— 它的后果严重得多。"""
        fake_checks(monkeypatch, model_warning="粤语特化版", provider_note="CUDA 不可用")
        assert "粤语" in host._caveat().detail


class TestReadiness:
    def test_not_ready_before_loading(self, host):
        assert not host.is_ready

    def test_ready_after_a_successful_load(self, host, monkeypatch):
        fake_checks(monkeypatch)
        host._on_loaded("some-model")
        assert host.is_ready

    def test_failure_with_a_live_old_engine_keeps_it_ready(self, host, monkeypatch):
        """**新模型没加载起来但旧的还活着时,不能把热键禁掉。**

        用户只是配置填错了,不该连原来能用的都没了。
        """
        fake_checks(monkeypatch)
        host._on_loaded("旧模型")
        host._on_failed("路径不存在", True)
        assert host.is_ready

    def test_failure_with_no_engine_left_blocks_recording(self, host):
        host._on_failed("模型文件缺失", False)
        assert not host.is_ready

    def test_ready_signal_carries_the_caveat(self, host, monkeypatch):
        fake_checks(monkeypatch, model_warning="粤语特化版")
        got = []
        host.ready.connect(lambda name, caveat: got.append((name, caveat)))
        host._on_loaded("m")
        assert got[0][0] == "m"
        assert isinstance(got[0][1], Caveat)

    def test_failed_signal_carries_whether_the_old_one_survives(self, host):
        got = []
        host.failed.connect(lambda msg, alive: got.append((msg, alive)))
        host._on_failed("坏了", True)
        assert got == [("坏了", True)]


class TestApplyDecidesForItself:
    """哪几项算"模型相关"由 EngineHost 自己知道。

    以前是调用方列一串 `cfg.engine.X != old.engine.X` —— 每加一个引擎
    配置项,那边的 if 就得跟着改一次,漏改的表现是
    **改了设置没生效,并且不报错**。

    另一面同样要紧:重载要 3 秒,而配置保存是防抖后批量发的 ——
    不相关的改动不能触发它。
    """

    def loads(self, host):
        seen = []
        host.loading.connect(lambda: seen.append(True))
        return seen

    def test_first_apply_loads(self, host):
        host._loaded_fingerprint = None
        seen = self.loads(host)
        host.apply(Config())
        assert seen == [True]

    def test_same_config_does_not_reload(self, host):
        host.load(Config())
        seen = self.loads(host)
        host.apply(Config())
        assert seen == []

    @pytest.mark.parametrize("field, value", [
        ("provider", "cuda"),
        ("num_threads", 12),
        ("use_itn", False),
        ("model_dir", "models/somewhere-else"),
    ])
    def test_engine_fields_trigger_a_reload(self, host, field, value):
        host.load(Config())
        seen = self.loads(host)
        cfg = Config()
        setattr(cfg.engine, field, value)
        host.apply(cfg)
        assert seen == [True], field

    def test_language_does_not_trigger_a_reload(self, host):
        """实测 auto 与 zh 输出逐字相同,而重载要 3 秒。"""
        host.load(Config())
        seen = self.loads(host)
        cfg = Config()
        cfg.engine.language = "zh"
        host.apply(cfg)
        assert seen == []

    def test_unrelated_config_does_not_trigger_a_reload(self, host):
        host.load(Config())
        seen = self.loads(host)
        cfg = Config()
        cfg.ui.theme = "dark"
        cfg.hotkey.paste = "<ctrl>+<alt>+j"
        host.apply(cfg)
        assert seen == []

    def test_load_always_reloads(self, host):
        """设置页那个「重新加载模型」按钮必须真的重载 ——
        用户点它正是因为怀疑模型状态不对。"""
        host.load(Config())
        seen = self.loads(host)
        host.load(Config())
        assert seen == [True]
