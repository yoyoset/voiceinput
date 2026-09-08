"""推理后端探测。

**这条路径是"静默失败"的教科书例子。** sherpa-onnx 的 CPU 版拿到
`provider="cuda"` 不会报错,只往 stderr 打一行:

    Please compile with -DSHERPA_ONNX_ENABLE_GPU=ON.
    Available providers: CPUExecutionProvider, . Fallback to cpu!

然后照常用 CPU 跑完。windowed 打包之后根本没有 stderr —— 界面写着 CUDA、
配置存着 cuda、实际跑在 CPU 上,没有任何地方会告诉用户。

而在这之前,界面上还写着"这台机器的显卡日常被 D2R 占满,选 CUDA 反而更慢"——
把开发机的具体情况当成了普遍事实告诉所有人。
"""

from pathlib import Path

from voiceinput.asr import providers


class TestAvailable:
    def test_cpu_always_available(self):
        """CPU 后端在任何发行包里都有,没有它整个程序就不能用了。"""
        assert providers.CPU in providers.available()

    def test_result_is_cached_and_stable(self):
        assert providers.available() is providers.available()

    def test_matches_what_is_on_disk(self):
        """探测结论必须和发行包里实际带的库对得上。

        不直接断言"这台机器有/没有 CUDA" —— 那样测试就变成了
        对开发机的断言,换台机器就红。
        """
        import sherpa_onnx

        root = Path(sherpa_onnx.__file__).resolve().parent
        has_cuda_lib = any(
            (d / marker).exists()
            for d in (root, root / "lib")
            for marker in providers._CUDA_MARKERS
        )
        assert (providers.CUDA in providers.available()) is has_cuda_lib


class TestResolve:
    def test_cpu_passes_through(self):
        assert providers.resolve("cpu") == ("cpu", "")

    def test_empty_defaults_to_cpu(self):
        assert providers.resolve("")[0] == "cpu"

    def test_case_insensitive(self):
        assert providers.resolve("CPU")[0] == "cpu"

    def test_unavailable_provider_falls_back_with_an_explanation(self):
        """**关键断言:落差必须带一句话说明。**

        静默回退正是这里要消灭的东西 —— 回退可以,不说不行。
        """
        actual, note = providers.resolve("nonexistent_provider")
        assert actual == "cpu"
        assert note, "回退了却什么都不说,用户会一直以为在用原来选的后端"

    def test_cuda_behaviour_follows_availability(self):
        actual, note = providers.resolve("cuda")
        if providers.is_available("cuda"):
            assert (actual, note) == ("cuda", "")
        else:
            assert actual == "cpu" and "CUDA" in note


class TestEngineUsesResolved:
    def test_engine_records_the_note(self, tmp_path):
        """引擎自己就要把 provider 落到能用的那个上,不能交给 sherpa-onnx 去回退。"""
        from voiceinput.asr.sensevoice import SenseVoiceEngine

        engine = SenseVoiceEngine(tmp_path, provider="nonexistent_provider")
        assert engine._provider == "cpu"
        assert engine.provider_note
