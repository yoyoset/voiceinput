# VoiceInput

按住热键说话,松开后文字直接出现在当前光标处。识别全程在本机完成,音频不上传。

主要用途是**对着 AI 说话代替打字**——文字进 Claude Code 的输入框和你手打没有区别,
该不该操作电脑由 AI 自己判断,这个工具不掺和。

## 快速开始

```bash
uv sync
uv run python -m voiceinput
```

首次运行会自动弹出**设置向导**,带你走完模型下载、麦克风标定、热键设置。
之后可以从托盘菜单「重新运行向导」再打开。

程序常驻系统托盘,双击托盘图标打开设置与历史。

### 向导第三步「标定麦克风」为什么重要

这一步会**真的录一句话跑一遍识别**,再按字错误率给结论,而不是只看电平。

因为电平只能证明"有声音进来",证明不了"那是你的人声、而且识别得出来"。
本机所有输入设备都是 RØDE Connect 的虚拟设备,系统默认的 `System Input`
通常是**系统声音回环**——它同样有电平,只看电平表根本分不出来。
选错的表现是"按了热键没反应",用户会怪程序,不会想到是设备选错了。

### 手动准备模型(可选)

向导能一键下载。要手动装的话:

```bash
curl -L -o sv.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
mkdir -p models && tar -xjf sv.tar.bz2 -C models/ && rm sv.tar.bz2
```

> **必须是 2024-07-17 这一版。** 同一个 release 页上的 2025-09-09 是粤语特化微调
> (ASLP-lab/WSYue-ASR),中英日韩全线崩坏,详见 [docs/engine-benchmark.md](docs/engine-benchmark.md)。
> 所以向导里**只提供这一个选项**——把两个只差日期的模型摆在一起只会让人选错。

## 默认热键

| 热键 | 行为 |
|---|---|
| `Ctrl + Alt + Space` | 按住说话,松开后把文字粘贴到光标处 |
| `Ctrl + Alt + Enter` | 同上,粘贴后再补一个回车(连续对话时用) |

都可以在「常规」页改。被别的程序占用时,`--selftest` 会报出来。

最早的默认是 `Ctrl + Win`,它会被 Ctrl+Win+任何键误触发(包括 Windows 切虚拟桌面),
所以换掉了,见 [docs/pitfalls.md](docs/pitfalls.md)「纯修饰键的热键会被它的每个超集触发」。

## 打包成便携版

```bash
uv run python build.py
```

产物在 `dist/VoiceInput/`,整个目录拷走即可在别的机器上跑。
打包完务必跑一次自检验证产物:

```bash
dist/VoiceInput/VoiceInput.exe --selftest
```

自检会检查模型文件、设备枚举、**模型加载与推理**、静音判定、Qt 与中文字形,
结果写在 `dist/VoiceInput/selftest.txt`。
**「PyInstaller 没报错」不等于产物能用**——这个项目就出过打包成功但 exe
完全起不来的情况(相对导入,见下),只有真跑一次才算数。

调试打包问题:

```bash
VOICEINPUT_CONSOLE=1 uv run python build.py   # 打出带控制台的版本,能看到 traceback
```

`VOICEINPUT_TRACE=1` 会让启动过程往 `startup-trace.txt` 逐步写面包屑。

**绿色软件**:配置(`config.toml`)、历史(`history.db`)、日志(`voiceinput.log`)
都生成在程序目录旁边,**不写注册表**。

唯一的例外是开机自启:它往启动文件夹(`%APPDATA%\...\Startup`)放一个快捷方式。
所以彻底卸载 = 删掉程序目录 **+** 删掉那个快捷方式(启用过的话)。
具体路径在程序的「关于」页里列着,那里也有直接打开目录的按钮。

## 设计取舍

**为什么走剪贴板而不是模拟按键**:同机的 [keytyper](../keytyper) 项目(Rust + enigo)
已经证明逐字符 VK 模拟打不出中文——`ascii_vk()` 对非 ASCII 返回 `None`。
所以这里用剪贴板 + Ctrl+V,并且粘贴后会**恢复原有剪贴板内容**。

**为什么不用现成的 OpenWhispr**:它的本地引擎只有 whisper.cpp 和 sherpa-onnx 的
Parakeet/Nemotron,而 Parakeet 不支持中文,没有 SenseVoice 选项。

**为什么用 SenseVoice 而不是 faster-whisper**:实测推理速度差 116 倍
(RTF 0.054 vs 6.317,同一句 5.6 秒的话 0.29s vs 37.6s)。
端到端(松开热键到 Ctrl+V 发出)实测 **380ms**,其中推理占 79%、
「粘贴前等待」占 21%,后处理和剪贴板加起来不到 1ms。
而且 SenseVoice 纯 CPU 就够,
不占显卡——这台机器的 GPU 日常被 4 个 D2R 实例占满。
代价是精度略逊,靠「词典」页的术语替换兜专有名词。

**为什么失败一定要有提示**:麦克风打不开、只录到静音、模型没加载——
这些如果静默失败,用户会以为没按到热键而反复重试。所以悬浮条上必须看得见,
这是「不做后台静默失败」这条原则的直接落地。

**为什么入口是根目录的 `entry.py` 而不是 `voiceinput/__main__.py`**:
PyInstaller 把入口当**顶层脚本**执行,`__package__` 为空,包内相对导入全部报
`ImportError: attempted relative import with no known parent package`。
而 `python -m voiceinput` 在源码环境下完全正常,所以这个 bug 本地测不出来。
入口逻辑放在 `voiceinput/cli.py`(包内,相对导入合法),外面两个薄壳用绝对导入。

## 已知问题 / 暂不处理

- **引擎精度尚未用真人语音定标**。目前的判断基于模型自带 test_wavs 和 TTS 合成音频,
  真人录音的 CER 还没测,见 `bench/record_samples.py`。如果实测发现 SenseVoice
  错得太多,可能要回头考虑云端 API 或加一层 LLM 纠错。
- **静音时模型会幻觉**。喂纯零会吐出 `그.` 这类内容。防线在音频层的
  `looks_silent()`(转写前就拦掉),文本层的 `is_effectively_empty()` 只是兜底。
- **只支持 Windows**。热键、剪贴板、自启都是 Windows 特定实现。
- **不做语音命令控制电脑**(Talon 那种范式)。语音只负责转成文字。

## 项目结构

```
entry.py           PyInstaller 入口(绝对导入,原因见上)
voiceinput/
  cli.py           入口逻辑 + 启动面包屑
  config.py        配置层(TOML,程序目录旁)
  audio.py         设备枚举、电平、录音
  asr/             引擎抽象 + SenseVoice 实现
  postprocess.py   纯函数:去标记、术语替换、中英空格
  metrics.py       纯函数:CER 与文本归一化(标定和 bench 共用)
  output.py        剪贴板 + Ctrl+V(含剪贴板备份恢复)
  hotkey.py        全局热键(push-to-talk / toggle)
  history.py       SQLite 历史
  download.py      模型下载解压(含目录穿越防护)
  autostart.py     开机自启(启动文件夹快捷方式,不写注册表)
  worker.py        模型加载与推理的工作线程
  selftest.py      自检:验证打包产物能不能真的跑
  app.py           主控:串起热键线程/识别线程/UI 线程
  ui/              主题、图标、悬浮条、托盘、主窗口、设置向导
bench/             引擎对比、样本录制、界面渲染
docs/              engine-benchmark.md(引擎实测)+ pitfalls.md(工程踩坑)
tests/             226 项测试
```

## 测试

```bash
uv run pytest tests/ -q
```

集成测试会加载真实模型跑真实音频;模型或 `bench/tts/` 不存在时自动跳过。
下载测试用本地 HTTP 服务模拟网络中断,不碰真实网络。
UI 测试用 offscreen 平台,不会弹窗。

> 渲染界面截图要用 `uv run python bench/render_ui.py`,**不能设
> `QT_QPA_PLATFORM=offscreen`**——offscreen 平台加载到的字体族是 0 个,
> 中文会全渲染成豆腐块,让人误以为程序有字体问题。
