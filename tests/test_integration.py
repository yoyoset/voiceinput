"""端到端:真实模型 → 真实音频 → 后处理链。

用的是 bench/gen_tts.ps1 合成的中英混说音频,内容已知,所以能断言具体输出。
模型或音频缺失时整组跳过,不让没准备环境的人卡在这里。

这组测试证明的是"链路通且结果稳定",不是"识别有多准"——
准确率要用真人录音测,见 docs/engine-benchmark.md。
"""

from pathlib import Path

import pytest

from voiceinput.asr.sensevoice import SenseVoiceEngine
from voiceinput.config import Config
from voiceinput.postprocess import clean, is_effectively_empty

ROOT = Path(__file__).parent.parent
MODEL_DIR = ROOT / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
TTS_DIR = ROOT / "bench" / "tts"

pytestmark = pytest.mark.skipif(
    not (MODEL_DIR / "model.int8.onnx").exists() or not TTS_DIR.is_dir(),
    reason="模型或 TTS 测试音频不存在",
)


@pytest.fixture(scope="module")
def engine():
    e = SenseVoiceEngine(MODEL_DIR, provider="cpu", num_threads=8)
    e.load()
    yield e
    e.unload()


def read_wav(path: Path):
    import soundfile as sf

    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    return audio[:, 0], sr


class TestEngine:
    def test_loads(self, engine):
        assert engine.is_loaded

    def test_pure_chinese_exact(self, engine):
        """纯中文实测是完全正确的,可以断言全等。

        注意标点是**全角**的:ITN 产出的是 `，` 和 `。`,不是半角。
        """
        audio, sr = read_wav(TTS_DIR / "tts_pure_zh.wav")
        result = engine.transcribe(audio, sr)
        assert clean(result.text) == (
            "我想做一个语音输入的工具，按住热键说话，松开之后文字直接出现在光标位置。"
        )

    def test_itn_produces_arabic_numerals(self, engine):
        """开了 ITN,"三十秒"应该输出成 "30 秒"。"""
        audio, sr = read_wav(TTS_DIR / "tts_digits.wav")
        text = clean(engine.transcribe(audio, sr).text)
        assert "30" in text
        assert "三十" not in text

    def test_code_switching_keeps_both_scripts(self, engine):
        """句内中英切换不能退化成单一语种。"""
        audio, sr = read_wav(TTS_DIR / "tts_mixed_2.wav")
        text = clean(engine.transcribe(audio, sr).text)
        assert "commit" in text.lower()
        assert "push" in text.lower()
        assert any("一" <= c <= "鿿" for c in text)

    def test_fast_enough_for_push_to_talk(self, engine):
        """RTF 必须远小于 1,否则 push-to-talk 体验不成立。

        实测约 0.05,这里放宽到 0.5——机器忙的时候会慢,但慢一个数量级
        就说明选型或配置出问题了。
        """
        audio, sr = read_wav(TTS_DIR / "tts_mixed_1.wav")
        result = engine.transcribe(audio, sr)
        assert result.rtf < 0.5, f"RTF {result.rtf:.3f} 太慢"

    def test_empty_audio(self, engine):
        import numpy as np

        result = engine.transcribe(np.zeros(0, dtype="float32"), 16000)
        assert result.text == ""

    def test_silence_hallucinates_so_audio_guard_is_required(self, engine):
        """**静音防线必须在音频层,不能指望模型返回空。**

        实测:喂 1 秒纯零,SenseVoice 会幻觉出 `그.`(韩文)。
        也就是说 `is_effectively_empty()` 拦不住它——那是文本层的兜底,
        只能挡住空串和纯标点。真正的防线是 app 里转写**之前**的
        `looks_silent()` 检查。这个测试就是钉住这个结论,
        免得以后有人把音频层的检查当成冗余给删了。
        """
        import numpy as np

        from voiceinput.audio import looks_silent

        audio = np.zeros(16000, dtype="float32")
        assert looks_silent(audio), "音频层必须能识别出这是静音"

        result = engine.transcribe(audio, 16000)
        if not is_effectively_empty(result.text):
            # 模型确实幻觉了,记下来当作已知行为
            assert clean(result.text), "幻觉内容非空,更加说明音频层的检查不可省"


class TestFullPipeline:
    def test_dictionary_fixes_proper_nouns(self, engine):
        """实测 SenseVoice 会把 keytyper/enigo 听错,词典要能兜住。

        断言的是"经过词典之后结果正确",而不是模型直接就对——
        后者不成立,这正是词典存在的理由。
        """
        cfg = Config()
        cfg.replacements = {
            "keyper": "keytyper", "aniggo": "enigo", "P test": "pytest",
            "hodkey": "hotkey",
        }
        audio, sr = read_wav(TTS_DIR / "tts_mixed_3.wav")
        raw = engine.transcribe(audio, sr).text
        text = clean(raw, cfg.replacements)
        assert "keytyper" in text
        assert "enigo" in text

    def test_spacing_normalized(self, engine):
        """模型输出的中英空格时有时无,后处理要统一。"""
        audio, sr = read_wav(TTS_DIR / "tts_mixed_1.wav")
        text = clean(engine.transcribe(audio, sr).text, {"P test": "pytest"})
        assert "function 改成" in text
        assert "改成 async" in text

    def test_output_is_single_line(self, engine):
        """粘到输入框的内容不该带换行。"""
        for name in ["tts_mixed_1", "tts_pure_zh", "tts_digits"]:
            audio, sr = read_wav(TTS_DIR / f"{name}.wav")
            assert "\n" not in clean(engine.transcribe(audio, sr).text)


class TestPipelineOverhead:
    """推理**之外**的步骤必须一直可以忽略。

    实测端到端 380ms 里推理占 300ms(79%),后处理和剪贴板各只要 0.1ms。
    引擎选型的全部依据是"推理快",如果哪天后处理变重了,这个论据就要重新说明 ——
    这条测试就是为了让那种变化立刻暴露,而不是慢慢地把体验磨没。
    """

    def test_postprocess_is_negligible(self):
        import time

        from voiceinput.postprocess import clean

        text = "<|zh|>把这个 function改成async,再跑一遍P test,然后commit" * 10
        rules = {f"词{i}": f"替换{i}" for i in range(200)}
        rules["P test"] = "pytest"

        t0 = time.perf_counter()
        for _ in range(100):
            clean(text, rules)
        per_call_ms = (time.perf_counter() - t0) / 100 * 1000

        # 实测 0.1ms 量级。放宽到 20ms —— 超了说明后处理里混进了重活儿
        assert per_call_ms < 20, f"后处理每次 {per_call_ms:.1f}ms,太重了"

    def test_dictionary_size_does_not_blow_up(self):
        """词典是单遍扫描的正则,条目变多不该让耗时爆炸。"""
        import time

        from voiceinput.postprocess import clean

        text = "把这个 function 改成 async"

        def timed(n: int) -> float:
            rules = {f"词{i}": f"替换{i}" for i in range(n)}
            t0 = time.perf_counter()
            for _ in range(50):
                clean(text, rules)
            return (time.perf_counter() - t0) / 50

        small, large = timed(10), timed(1000)
        # 100 倍的词典不该带来 100 倍的耗时
        assert large < small * 30 + 0.01, f"{small * 1000:.2f}ms -> {large * 1000:.2f}ms"
