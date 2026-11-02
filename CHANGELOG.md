# Changelog

项目此前没有变更日志，历史以 git 提交信息为准。下面从 2026-11-02 开始记录。

## 2026-11-02 — 模型/运行时评估（未改动）

**结论：不换模型，不升运行时。** SenseVoice-Small int8 **2024-07-17** 仍是默认且唯一选项
（实测 CPU 18 倍实时、端到端约 0.38 秒，见 `docs/engine-benchmark.md`；2025-09-09 版是粤语特化，不是升级）。

候选（都**没有**实测过，仅供下次评估）：
- sherpa-onnx 已带 Qwen3-ASR-0.6B、Fun-ASR-Nano 等离线包。Qwen3-ASR-1.7B 官方表在中文/方言上 WER 明显低于
  Whisper-large-v3（厂商自报），支持日语；换之前要用 `bench/` 在本机真实录音上对比字错误率与延迟。
- sherpa-onnx 已发布 v2.0.x（大版本，当前 pin 1.13.6）；升级前注意 `sherpa-onnx-core` 要同装的老坑。

**遗留**：精度仍未用真人语音定标（见 README「已知问题」）。
