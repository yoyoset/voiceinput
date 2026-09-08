# 引擎实测记录

记录引擎选型与性能的实测数字,不是复述文档。所有"已确认"都指真的跑过并核对了输出。

打包、Qt、音频、状态机方面的坑在 [pitfalls.md](pitfalls.md)。

---

## 测试环境(已确认)

| 项 | 值 |
|---|---|
| CPU | Xeon E5-2698 v3 @ 2.30GHz,16 核 32 线程(2014 年架构,单核弱) |
| GPU | RTX 3060 **12GB**,驱动 610.74 |
| Python | 3.13.14 |
| sherpa-onnx | 1.13.6 |
| 音频输入 | RØDE Connect 虚拟设备(System / Stream / Virtual Input) |

---

## `sherpa-onnx` 被 Windows 自带的 onnxruntime.dll 劫持

**现象**:调 `OfflineRecognizer.from_sense_voice()` 直接 C++ 层硬退出(Python 的
`try/except` 抓不到,连之前 `print` 的内容都因为没 flush 而丢失),只在 stderr 留一行:

```
The given version [27] is not supported, only version 1 to 10 is supported in this build.
```

**排查过程(值得记,因为前两个假设都错了)**:

1. 最初以为是模型 ONNX IR 版本太新 → **实测否定**。手工解析 protobuf 头,
   `ir_version = 7`,很老,没问题。
2. 接着以为是 `faster-whisper` 带进来的 `onnxruntime` 1.29 pip 包冲突
   (1.29 的 `ORT_API_VERSION` 恰好 = 27,数字对上了,看着很像) → **实测否定**。
   `uv remove faster-whisper` 之后错误一模一样。
3. 真正原因:`C:\Windows\System32\onnxruntime.dll` —— Windows 自带一个老版
   onnxruntime,只实现到 ORT API version 10。而 PyPI 上的 `sherpa-onnx` wheel 里
   只有 `_sherpa_onnx.cp313-win_amd64.pyd`,**不含 onnxruntime.dll**,于是被
   System32 那个顶包。

**解法**:显式安装 `sherpa-onnx-core`,它会把匹配版本的 `onnxruntime.dll`
放在 `.pyd` 旁边,DLL 搜索顺序优先命中它。

```bash
uv add sherpa-onnx sherpa-onnx-core
```

**为什么容易掉进去**:`uv pip install sherpa-onnx` 会连带装上 `sherpa-onnx-core`,
但 `uv add sherpa-onnx` **不会**。同一台机器、同一个包名,两条命令结果不同,
所以"我明明装过能用"这种记忆完全靠不住。

---

## 2025-09-09 版 SenseVoice 是粤语特化模型,不是原版升级

sherpa-onnx 的 release 页上有两个 SenseVoice int8 模型,名字只差日期,
很容易以为新的就是升级版:

- `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-**2024-07-17**`
  → 来自 `FunAudioLLM/SenseVoice`,**通用原版**
- `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-**2025-09-09**`
  → 来自 `ASLP-lab/WSYue-ASR/sensevoice_small_yue`,**粤语微调版**
  (`test_wavs/` 里 23 个样本有 20 个是 `yue-*.wav`,是个明显信号)

用模型自带 test_wavs 跑的对比(CPU,threads=8,`use_itn=True`):

| 样本 | 2024-07-17(原版) | 2025-09-09(粤语版) |
|---|---|---|
| zh | 开饭时间早上9点至下午5点。 | 放时间早上九点至下午五点 |
| en | The tribal chieftain called for the boy and presented him with 50 pieces of code. | THE TRIVBAL CHIEF THIN CALLED FOR THE BOY AND PRESENTED HIM WITH FIFTY PIECES OF COOD |
| ja | うちの中学は弁当制で持っていきない場合は50円の学校販売のパンを買う。 | 家中学便当制持合五十円学校悭売借 |
| ko | 조금만 생각을 하면서 살면 훨씬 편할 거야. | 如万醒 하면서面 훨씬过呀 |
| yue | 呢几个字都表达唔到我想讲嘅意思。 | 呢几个字都表达唔到我想讲嘅意思 |

粤语版除粤语外全线崩坏:中文吞字("开"没了)、英文拼错、日韩基本不可用,
而且**丢失标点和 ITN**(原版输出 `9点`/`5点` + 句号,粤语版是 `九点`/`五点` 无标点)。

**结论:用 2024-07-17。**

---

## faster-whisper 走 GPU 要自己补 CUDA 运行时

`WhisperModel(..., device="cuda")` 构造**不会报错**——CTranslate2 是惰性加载,
真正调 `transcribe()` 时才炸:

```
RuntimeError: Library cublas64_12.dll is not found or cannot be loaded
```

装了 NVIDIA 驱动不等于有 CUDA 运行时库。补:

```bash
uv pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

**注意这个坑只影响 faster-whisper。** SenseVoice 走 CPU 就够快(见下),
完全不碰 CUDA,这也是它作为产品引擎的一个额外好处:少一整条依赖链。

---

## 关键结论:CPU 就够,不需要 GPU

原版模型在这台机器**纯 CPU** 上的表现:

| threads | 音频总长 | 推理总耗时 | RTF | 倍速 |
|---|---|---|---|---|
| 8 | 29.7s | 1.62s | 0.054 | **18.4x 实时** |
| 4 | 29.7s | 1.93s | 0.065 | **15.4x 实时** |

模型加载约 3.0s(一次性,常驻后不再产生)。

一句 5 秒的话,推理约 **0.29s**。**原计划里"CUDA/cuDNN 版本装不上"这个风险项
直接作废,不装 CUDA。**

### 但用户感受到的不是这个数字

上面是**推理耗时**。真正该拿来说事的是"松开热键到文字出现"的整段。
这个数字一直没测过 —— 引擎选型的依据全建立在推理那一项上,
而后处理、剪贴板、粘贴前等待都没算进去。

`bench/latency.py` 实测(5 条样本 × 5 轮):

| 阶段 | 中位数 | 占比 |
|---|---|---|
| 推理 | 300.1 ms | 79% |
| 后处理 | 0.1 ms | ~0 |
| 写剪贴板 | 0.1 ms | ~0 |
| 粘贴前等待(配置项) | 80.0 ms | 21% |
| **合计** | **380.3 ms** | |

三个结论:

1. **选型依据成立** —— 推理仍占 79%,后处理和剪贴板加起来不到 1ms,
   没有藏在别处的开销。
2. **文档之前只说 0.29s,低估了约 30%。** 诚实的说法是端到端约 0.38 秒。
3. **其中 80ms 是我们自己配的等待**(`output.paste_delay_ms`),
   占了 21%。粘贴稳的应用可以调小它换取更跟手的手感 ——
   这是唯一一项用户能自己优化的。

(Ctrl+V 发出之后还有目标应用自己的粘贴耗时,那取决于对方,测不了。)

顺带算一下换算到端到端的对比:faster-whisper 那 37.6s 推理加上同样的
固定开销约 37.7s,所以"快 116 倍"落到用户体感上约是 **99 倍** —— 依然压倒性,
但这个数字才是诚实的。

`tests/test_integration.py::TestPipelineOverhead` 钉住了"推理之外的步骤必须
一直可以忽略",防止将来往后处理里加重活儿把这个结论慢慢磨掉。

---

## 这台机器的 GPU 平时是被占满的

跑 faster-whisper GPU 版时,进程起来了、CPU 在烧,但十分钟出不来一条结果。
`nvidia-smi` 一看:

```
utilization.gpu = 100%, memory.used = 11577 MiB / 12288 MiB
```

占用方是**四个 Diablo II Resurrected 实例**(外加 Chrome / Edge / 微信 / Epic 等一堆
`C+G` 进程)。我们的 python 确实以 `C`(compute)上了 GPU,但在跟 4 个 D2R 抢,
所以只能爬。

**这条对选型是决定性的,不只是个测试环境问题**:语音输入工具的前提是
"用户在干别的事情时随手按热键说一句"——而这台机器"干别的事"经常就是多开 D2R。
一个需要独占 GPU 才有速度的引擎,在真实使用场景里恰好是最不可用的。

`nvidia-smi --query-compute-apps` 在非管理员下 per-process 显存显示 `[N/A]`,
要看全貌得跑完整的 `nvidia-smi`。

---

## TTS 预探:SenseVoice 能处理句内中英切换,错的是专有名词

用 Windows SAPI 的 Huihui(zh-CN)合成 5 句中英混说测试音频
(`bench/gen_tts.ps1` + `bench/tts_sentences.json`),跑 2024-07-17 原版:

| 原文 | SenseVoice 输出 |
|---|---|
| 把这个 function 改成 async，再跑一遍 pytest | 把这个 function改成async再跑一遍 **P test**。 |
| 这个 commit 先别 push，我要改一下 config 里的 hotkey | 这个commit先别push，我要改一下config里的 **hodkey**。 |
| 帮我看一下 keytyper 项目的依赖，enigo 是什么版本 | 帮我看一下 **keyper** 项目的依赖 **aniggo** 是什么版本。 |
| 我想做一个语音输入的工具，按住热键说话，松开之后文字直接出现在光标位置 | 完全正确 |
| 把超时改成三十秒，采样率用十六千赫兹，单声道就够了 | 把超时改成30秒，采样率用16000赫兹单声道就够了。 |

结论:

1. **句内中英切换结构上没问题**——不会退化成单一语种,中英能出现在同一句里。
2. **常见英文词没问题**:function / async / commit / push / config 全对。
3. **错的全是复合词和专有名词**:pytest、hotkey、keytyper、enigo。
   这正是术语替换词典要解决的问题,但**先等真人录音确认这些词真的会错**再做。
4. **ITN 工作正常**:三十→30、十六千赫兹→16000赫兹,还自动补了标点。
5. `language="auto"` 与 `language="zh"` 输出**逐字相同**,这个参数在混说场景不起作用,
   不用在它上面纠结。
6. 输出的空格不一致(`把这个 function改成async`),postprocess 需要规整 ASCII 段前后的空格。

**这组数据的局限必须讲清楚**:是中文 TTS 念的英文,发音本身就不标准,对引擎不公平。
真人清楚地说 "pytest" 大概率能识别对。所以它只能说明能力的**形状**
(哪类词危险),**不能替代真实录音**,更不能拿来定 CER。

---

## faster-whisper large-v3 对照:更准,但慢到不可用

GPU 路线在这台机器上走不通(坑 5),改用 CPU + int8 跑同一批 test_wavs。
**准确率与设备无关,所以精度对比依然成立;速度数字则要结合坑 5 一起看。**

### 速度:差 116 倍

| 引擎 | 配置 | RTF | 倍速 | 5.6s 的一句话要多久 |
|---|---|---|---|---|
| SenseVoice-Small int8 | CPU, 8 线程 | **0.054** | **18.4x 实时** | **0.29s** |
| faster-whisper large-v3 | CPU, int8 | 6.317 | 0.2x 实时 | **37.6s** |

模型加载:SenseVoice 2.9s / faster-whisper 19.5s。

对 push-to-talk 来说 37 秒是彻底出局——说完一句话要等半分多钟才出字。
而 GPU 那条路在这台机器上被 4 个 D2R 堵死。

### 精度:faster-whisper 明显更好(**这里要修正我先前的判断**)

先前我在坑 2 里拿 2024 版 SenseVoice 的输出当"正确答案"来对比粤语版,
**那个对比本身成立(粤语版确实全线崩坏),但不能推出 SenseVoice 的输出就是对的**。
把 faster-whisper 摆进来之后,SenseVoice 的错处就露出来了
(这几条 test_wavs 官方没给 ground truth,下面是按语义/语法常识判断):

| 样本 | SenseVoice | faster-whisper | 谁更可信 |
|---|---|---|---|
| zh | 开**饭**时间早上9点至下午5点。 | 开**放**时间早上9点至下午5点 | fw。"开放时间 9-5" 是自然说法,"开饭时间 9 点到 5 点"讲不通 |
| en | ...fifty pieces of **code**. | ...fifty pieces of **gold**. | fw。部落酋长给男孩 "pieces of gold" 才通 |
| ja | 持ってい**きない**場合は | 持ってい**けない**場合は | fw。SenseVoice 那个不合语法 |
| ko | 조금만 생각을 하면서 살면 훨씬 편할 거야. | 同左 | 平手 |
| yue | 呢几个字都表达唔到我想讲嘅意思 | 這幾個字都表達不到我想說的意思 | 行为不同:SV 保留粤语口语,fw 转成书面中文。看需求 |

**所以真实的权衡是:SenseVoice 快 116 倍但会错词,faster-whisper 准但在这台机器上没法用。**
不是"SenseVoice 全面胜出"。这个判断只能靠真人录音来定——
如果 SenseVoice 在你自己的语音上错得不多,那速度优势压倒一切;
如果错得让你每次都要动手改,那就得重新考虑(云端 API、或 SenseVoice 加一层纠错)。

---

## SenseVoice 对静音会产生幻觉

喂 1 秒纯零进去,输出不是空串,而是 `그.`(韩文)。

**所以防线必须在音频层,不能指望模型返回空。** `postprocess.is_effectively_empty()`
只能挡住空串和纯标点,挡不住这种"看起来像正常文本"的幻觉。
真正生效的是 `app._finish_recording()` 里转写**之前**的 `looks_silent()` 检查
(RMS < -50 dBFS 直接拒绝)。

`tests/test_integration.py::test_silence_hallucinates_so_audio_guard_is_required`
钉住了这个结论,免得以后有人觉得音频层的检查是冗余给删掉。

---

## 待补:真实语音对比(需要录样本)

上面用的是模型自带 test_wavs,只能证明通路和速度,**不能回答最关键的问题**:
中英混说的技术术语(如"把这个 function 改成 async")识别得怎么样。
SenseVoice 每段解码只挂一个语种标签,句内中英混合正是它可能吃亏的地方,
而这恰好是本项目的主场景。

需要跑 `bench/record_samples.py` 录真实样本后,再跑:

```bash
# SenseVoice(主环境)
uv run python bench/run_sensevoice.py --model-dir models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17 --out bench/results/sv-cpu-auto.json

# faster-whisper(独立 venv,原因见坑 1)
C:/Users/yoyos/AppData/Local/Temp/claude/fwbench/Scripts/python.exe bench/run_fasterwhisper.py --out bench/results/fw-large-v3.json

# 汇总
uv run python bench/report.py bench/results/*.json -o docs/engine-benchmark-real.md
```

## 待确认:哪个输入设备是麦克风

本机所有输入设备都是 RØDE Connect 的虚拟设备,默认输入是 "System Input"——
在 RØDE Connect 里这个名字通常指**系统声音回环而不是话筒**。
录样本前必须先跑 `bench/probe_devices.py` 用电平实测确认,不能靠名字猜。
