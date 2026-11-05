# HANDOFF：写给接手 VoiceInput 的下一个 AI

你好。这封交接信是 2026-11-05 写的（Claude Opus 5.5）。它把之前几轮会话（2026-08-26 起）的记忆、提交记录和文档汇到一起，告诉你项目是什么、现在走到哪了、怎么构建测试打包发布、为什么这样设计、踩过哪些坑、还有什么没修、哪些事不要做。

**最重要的一份文档是 [docs/pitfalls.md](docs/pitfalls.md)**。它有一千多行，每条都写了"现象、原因、修法和教训"。改哪块代码之前，先在它的目录里找对应的那一节。这封信只挑最要紧的几条。

> 用户的全局工作原则，照做：先实测再下结论；实测和早先的假设矛盾时，如实写"以为是 A，实测是 B"；绝不能出现"后台失败，用户以为成功"；只按路径 `git add`，每个独立改动单独提交，commit message 写真实依据；构建和测试全绿才提交。
> 机器是 Windows，主 shell 是 PowerShell，git bash 在 `D:\PortableGit\bin\bash.exe`。
> 用户还说过：**别用 computer-use 去操作他的电脑做实测，太慢**。把测试步骤写给他，他来测，再把结果告诉你。

---

## 1. 项目是什么，现在什么状态

按住热键说话，松开后文字直接出现在光标处。主要用途是**对着 AI 说话来代替打字**。它不是语音助手，也不能用语音控制电脑；接到文字后该不该动手，由接收文字的那一方决定。
技术栈：PySide6 界面，SenseVoice-Small int8（2024-07-17 版）通过 sherpa-onnx 纯 CPU 推理，用剪贴板加 Ctrl+V 输出（会备份并恢复原剪贴板），历史记录存 SQLite，打包用 PyInstaller 出绿色版。只支持 Windows。

**v0.1.0（2026-11-02）已公开发布：**
- 仓库 `yoyoset/voiceinput` 是 public。11-02 才第一次推代码，之前是空仓库。
- Release：https://github.com/yoyoset/voiceinput/releases/tag/v0.1.0 ，文件是 `VoiceInput-0.1.0-win-x64.zip`（216,606,621 B），**包含模型**，sha256 `58C915086A2E8B146B6746893143129DD355A88E3099ABBD51206F4E13B78238`。
  之所以把模型打进包：首次运行的下载向导是图形界面，当时没法在自动化环境里实测，所以干脆带上。
- squareuncle.com 下载页已经上架，博客 11-04 发布。这两样在 SUBLOG 仓库，不归这个仓库管。
- README 是面向用户写的（为什么做、6 张截图、实测数据、隐私说明、FAQ、赞助），另有 MIT LICENSE、第三方许可证表和 CHANGELOG。
- 测试 755 项（11-02 时全部通过）。

## 2. 命令（README 里有，这里汇总）

```bash
uv sync                                   # Python 3.13 + uv
uv run python -m voiceinput               # 从源码运行
uv run pytest tests/ -q                   # 测试，纯函数为主，不需要麦克风和网络
uv run --group dev python build.py        # 打包 → dist/VoiceInput/（会自动备份、还原用户数据，见坑 1）
dist/VoiceInput/VoiceInput.exe --selftest # 打包后必须跑一次，结果写到 selftest.txt
VOICEINPUT_CONSOLE=1 uv run --group dev python build.py   # 打一个带控制台、能看到 traceback 的版本
uv run python bench/render_ui.py          # 重新生成 README 截图（输出到 bench/shots/）
```

**发布流程（v0.1.0 是手动做的，没有脚本）：**
1. `build.py`，然后在 `dist/VoiceInput/` 上跑 `--selftest`。
2. **把 `dist/VoiceInput/` 整个拷到别的目录**，在拷贝里删掉 `history.db`（用户说过的话）、`config.toml`、`voiceinput.log`、`selftest.txt`、`startup-trace.txt`。
   **绝对不能直接压缩 `dist/VoiceInput/`**，因为开发机上的那份就是用户每天在用的那份。
3. 压缩成 `VoiceInput-<ver>-win-x64.zip`，解压到一个新目录，再跑一次 `--selftest`。
4. 上传：`& "C:\Program Files\GitHub CLI\gh.exe" release create v<ver> <zip> --repo yoyoset/voiceinput ...`。gh 要写全路径，账号 yoyoset 已登录。上传后把文件下载回来核对 sha256。
5. 第 2 步应该写成脚本，并让脚本在发现用户数据时拒绝出包（comicgen 的 `scripts/build_release.py` 就是这么做的）。**这个还没做。**

## 3. 关键决策和为什么

1. **用 SenseVoice-Small，不用 Whisper**：在这台机器上纯 CPU 能跑到 15–18 倍实时，端到端约 380 ms；faster-whisper large-v3 走 CPU 是 0.2 倍实时，慢 116 倍。GPU 路线也不可行，因为用户的 RTX 3060 平时被 4 个 D2R 游戏实例占满。
   代价是精度：在官方测试音频上，它把"开放时间"听成"开饭时间"。**一直没有用真人录音测过字错误率（CER）**，这是最大的遗留问题。
   **不要用 2025-09-09 版**，那是粤语特化版，中英日韩全线崩坏。
2. **2026-11-02 评估过换模型或升级运行时，结论是不换**（见 CHANGELOG）。Qwen3-ASR、Fun-ASR-Nano 等候选**都没实测过**。
3. **用剪贴板加 Ctrl+V，不模拟逐字打字**：用户的另一个项目 `F:\my_ai\keytyper` 已经证明，逐字符模拟按键打不出中文。
4. **不用现成的 OpenWhispr**：它的本地引擎不支持 SenseVoice，中文正是它的短板。
5. **首次运行向导会真的录一句话、跑识别、算 CER**，不只看电平。原因是开发机上的输入设备都是 RØDE Connect 的虚拟设备，系统声音回环同样有电平，光看电平表分不出是不是话筒。
6. **绿色软件**：配置、历史、日志都放在 exe 旁边，不写注册表；开机自启用启动文件夹里的快捷方式。
7. **界面不能把开发机上的情况当成事实写出来**：设备、性能、显卡、热键是否被占用，一律在运行时探测，探测不到就显示"不知道"。曾经界面上写着"这台机器所有输入设备都是 RØDE"，被用户指出来过。

## 4. 最要紧的坑（完整版见 docs/pitfalls.md）

1. **重新打包会删掉用户数据**：`build.py` 会 `rmtree` 整个 `dist`，而用户的配置和历史就在里面。2026-08-26 真的删过一次，没法恢复。现在由 `rescue_user_data()` / `restore_user_data()` 自动备份和还原（测试在 `tests/test_build_userdata.py`）。**不要把这段逻辑"简化"掉。**以后新增任何放在程序目录里的用户文件，都要加进 `USER_DATA`。
2. **sherpa-onnx 被 System32 里的老 onnxruntime.dll 顶替**：报错 `The given version [27] is not supported, only version 1 to 10`，在 C++ 层硬退出，Python 的 try 抓不到。解法是显式安装 `sherpa-onnx-core`。注意 `uv add sherpa-onnx` **不会**带上 core（`uv pip install` 会），所以要写成 `uv add sherpa-onnx sherpa-onnx-core`。
3. **PyInstaller 入口不能用 `voiceinput/__main__.py`**：相对导入会全部失败。windowed 版的表现是**静默卡死**（其实是弹了一个看不见的错误框在等人点）。入口用根目录下的 `entry.py`，里面写绝对导入。
4. **Qt offscreen 平台没有字体**：截图里中文全是豆腐块，但程序本身没问题。截图要用 windows 平台，并且不调 `show()`，用 `QWidget.grab()` 截。
5. **"恢复剪贴板"只对纯文本成立**：图片和富文本以前会被静默丢掉，后来修了。修的时候在用户的真实剪贴板上做过破坏性实验，**别再这么做**。
6. **点托盘图标会抢焦点**：`SetForegroundWindow` 返回成功后，前台窗口要约 300 ms 才真正回到原窗口，所以要轮询等它落定（见 `focus_tracker.py`）。
7. **悬浮麦克风"消失"有两种情况**：一种是被最小化或隐藏；另一种是系统的置顶层级错乱，带 TOPMOST 的窗口沉到了普通窗口下面（同一时刻 explorer 的副屏任务栏也一样）。现在巡检发现"有非置顶的可见窗口排在我前面"时，就重新设一次置顶（commit 4481859）。**不要每 3 秒无条件重设**，那样会和别的置顶程序互相抢。
8. **纯修饰键组合的热键会被它的每个更大组合触发**；凭印象推荐"应该没人用"的热键组合，实测已经被占用了。现在用 `RegisterHotKey` 当场问 Windows。
9. **WASAPI 采样率不匹配，曾导致一半的麦克风选项打不开**；设备编号会变，所以按设备名存，不按编号存。
10. **曾经一直把"推理耗时"当成"用户感受到的延迟"**；用户真正感受到的是从松开热键到文字出现的端到端时间（380 ms）。
11. **CER 会把正确的数字规整化（ITN）输出判成大面积错误**，所以要先归一化再比较（`metrics.py`）。
12. **挑部分改动暂存时别用 `git apply --cached --unidiff-zero`**：纯插入的 hunk 会被放错行，而且不报错。要用 `git hash-object -w --stdin` 加 `git update-index --cacheinfo`，暂存后先 `ast.parse` 检查一遍。
13. **在导入时算好的默认路径**，曾经让测试写进了真实的历史数据库。测试一律用临时目录。

## 5. 已知但还没处理的问题

- **精度没有用真人语音定标**。`bench/record_samples.py` 已经写好，还没有系统地录过。
- **发布打包没有脚本**（见 §2 第 5 步），现在靠人记得剔除用户数据。
- 喂纯静音时模型会幻觉出 `그.` 之类的输出。现在用 `looks_silent()` 先拦一道，文本层再兜一次底。
- 安装包没有签名。只支持 Windows。
- 不带模型、首次运行再下载的那条路径，没有在自动化环境里端到端测过（这就是 v0.1.0 带模型的原因）。

## 6. 不要做的事

- 不要直接压缩开发机上的 `dist/VoiceInput/`，也不要上传，里面有 `history.db`。
- 不要 `git add -A` / `git add .`；工作区里有 `history.db`、日志、`selftest.txt` 这些运行时文件（已 gitignore，但还是要小心）。
- 不要在用户的真实剪贴板、真实历史库上做破坏性实验。
- 不要把开发机的硬件情况写进界面文案。
- 不要换成 2025-09-09 版的 SenseVoice。
- 不要用 computer-use 操作用户的电脑做实测；写清楚步骤，交给用户来测。
