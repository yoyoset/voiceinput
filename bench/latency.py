"""端到端延迟:松开热键 → 文字出现在光标处。

**为什么单独测这个**:docs 里的 0.29s 是**推理耗时**,而用户感受到的是整段:
停止录音 → 推理 → 后处理 → 写剪贴板 → 等待 → 发 Ctrl+V。
引擎选型的依据一直是推理那个数字,但没人验证过整段有多长。
如果后面几步吃掉了大头,"快 116 倍"这个论据的实际意义就要打折。

不碰真实按键(那会往当前窗口打字),只测到"Ctrl+V 被派发"为止,
并把配置里的等待时间如实计入。

用法:
    uv run python bench/latency.py
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).parent.parent))

import soundfile as sf  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from voiceinput.asr.sensevoice import SenseVoiceEngine  # noqa: E402
from voiceinput.config import Config  # noqa: E402
from voiceinput.output import TextOutput  # noqa: E402
from voiceinput.postprocess import clean  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
MODEL_DIR = ROOT / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
ROUNDS = 5


class FakeKeyboard:
    """记录按键但不真的发出去 —— 否则会往跑测试的窗口里打字。"""

    def __init__(self) -> None:
        self.events: list = []

    def press(self, key) -> None:
        self.events.append(key)

    def release(self, key) -> None:
        pass


def pick_samples() -> list[Path]:
    tts = ROOT / "bench" / "tts"
    if tts.is_dir():
        found = sorted(tts.glob("*.wav"))
        if found:
            return found
    return sorted((MODEL_DIR / "test_wavs").glob("zh.wav"))


def main() -> int:
    if not (MODEL_DIR / "model.int8.onnx").exists():
        print(f"模型不存在: {MODEL_DIR}")
        return 1
    samples = pick_samples()
    if not samples:
        print("没有可用的测试音频")
        return 1

    app = QApplication.instance() or QApplication([])   # noqa: F841
    cfg = Config()

    engine = SenseVoiceEngine(MODEL_DIR, num_threads=cfg.engine.num_threads)
    t0 = time.perf_counter()
    engine.load()
    load_s = time.perf_counter() - t0
    print(f"模型加载: {load_s:.2f}s(一次性)\n")

    kb = FakeKeyboard()
    out = TextOutput(
        restore_clipboard=cfg.output.restore_clipboard,
        paste_delay_ms=cfg.output.paste_delay_ms,
        send_delay_ms=cfg.output.send_delay_ms,
        keyboard=kb,
    )

    stages: dict[str, list[float]] = {"推理": [], "后处理": [], "剪贴板": []}
    audio_total = 0.0

    for wav in samples:
        audio, sr = sf.read(wav, dtype="float32", always_2d=True)
        audio = audio[:, 0]
        for _ in range(ROUNDS):
            t = time.perf_counter()
            result = engine.transcribe(audio, sr)
            stages["推理"].append(time.perf_counter() - t)

            t = time.perf_counter()
            text = clean(result.text, cfg.replacements)
            stages["后处理"].append(time.perf_counter() - t)

            t = time.perf_counter()
            out._write_clipboard(text)
            stages["剪贴板"].append(time.perf_counter() - t)
        audio_total += len(audio) / sr

    engine.unload()

    print(f"样本 {len(samples)} 条 × {ROUNDS} 轮,音频共 {audio_total:.1f}s\n")
    print(f"{'阶段':<14}{'中位数':>10}{'最大':>10}")
    print("-" * 34)
    measured = 0.0
    for name, values in stages.items():
        med = statistics.median(values)
        measured += med
        print(f"{name:<14}{med * 1000:>8.1f}ms{max(values) * 1000:>8.1f}ms")

    # 配置里的固定等待,是真实延迟的一部分,不能不算
    print(f"{'粘贴前等待':<14}{cfg.output.paste_delay_ms:>8.1f}ms   (配置)")
    total = measured + cfg.output.paste_delay_ms / 1000

    print("-" * 34)
    print(f"{'合计':<14}{total * 1000:>8.1f}ms")
    print()
    print("这是**松开热键到 Ctrl+V 被发出**的时间。之后还有目标应用自己的")
    print("粘贴耗时,那部分取决于对方,测不了。")
    print()
    infer_med = statistics.median(stages["推理"])
    print(f"推理占比: {infer_med / total:.0%} —— "
          f"{'推理仍是大头,选型依据成立' if infer_med / total > 0.5 else '推理之外的开销已经超过一半,选型依据要重新说明'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
