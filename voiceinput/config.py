"""配置层:所有用户可调参数的单一来源。

绿色软件原则:配置写在程序目录旁边的 config.toml,不碰注册表、不写 AppData。
整个目录拷走就能换机器用。

设计取舍:用 dataclass 而不是裸 dict,是为了让"有哪些配置项、类型是什么、默认值多少"
在一个地方说清楚,UI 层可以直接照着渲染,不用两边对着改。
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


def app_dir() -> Path:
    """程序所在目录。打包成 exe 后是 exe 旁边,开发时是项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = app_dir() / "config.toml"
DEFAULT_MODEL_DIR = "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"


@dataclass
class AudioConfig:
    device: int | None = None
    """输入设备编号。None = 系统默认。

    系统默认输入设备经常不是话筒(虚拟声卡、立体声混音、各种 loopback
    都会占着默认位置),所以设置界面里必须让用户自己挑并看到电平。

    **这个编号只是缓存,不是身份。** PortAudio 的 index 是枚举序号,
    插拔任何音频设备都会重排 —— 认编号会在某天悄悄录到别的设备上。
    真正的身份是下面的 name + hostapi。
    """
    device_name: str = ""
    """设备名。**这才是设备的身份。** 启动时按它去找编号。"""
    device_hostapi: str = ""
    """设备所属的 hostapi(MME / Windows WASAPI …)。

    同一个物理设备在多个 hostapi 下各出现一次、名字完全相同,
    只认名字会挑错那一个。
    """
    max_seconds: float = 120.0
    """单次录音上限。防止热键卡住导致无限录音吃满内存。"""

    # **采样率不是配置项。** SenseVoice 要 16kHz;声明成别的值 sherpa-onnx
    # 会内部重采样、不报错,但识别质量**静默下降**(实测声明 44100 时
    # "开饭"变成了"下饭")。这种改了不报错只是悄悄变差的旋钮,
    # 摆出来只会害人,所以直接用 audio.SAMPLE_RATE 常量。


@dataclass
class EngineConfig:
    name: str = "sensevoice"
    model_dir: str = DEFAULT_MODEL_DIR
    provider: str = "cpu"
    num_threads: int = 8
    language: str = "auto"
    """SenseVoice 的语种标签。实测 auto 与 zh 输出逐字相同,保留是为了以后换引擎。"""
    use_itn: bool = True
    """逆文本归一化:开了才有标点和阿拉伯数字。"""


@dataclass
class HotkeyConfig:
    paste: str = "<ctrl>+<alt>+<space>"
    """按住说话、松开粘贴。pynput 的组合键写法,<cmd> 在 Windows 上是 Win 键。

    **默认值只是起点,不是结论。** 哪个组合真的空闲取决于这台机器上装了什么,
    向导会当场探测(见 conflict.py),撞了就换。

    早先的默认是 `<ctrl>+<cmd>` —— 纯修饰键组合,结果是**任何 Ctrl+Win+X
    都会触发它**:Windows 自己的虚拟桌面切换、别的软件的热键,统统算。
    用户报的"和微信撞了"就是这个。所以现在一定带一个普通键。
    """
    paste_and_send: str = "<ctrl>+<alt>+<enter>"
    """粘贴后再补一个回车,对着 Claude Code 连续对话时用。"""
    mode: str = "push_to_talk"
    """push_to_talk = 按住说话松开结束;toggle = 按一下开始再按一下结束。"""


@dataclass
class OutputConfig:
    restore_clipboard: bool = True
    """粘贴后恢复用户原有的剪贴板内容。默认开,不能默默吞掉人家复制的东西。"""
    paste_delay_ms: int = 80
    """写入剪贴板到发送 Ctrl+V 之间的等待。太短某些应用会粘到旧内容。"""
    send_delay_ms: int = 60
    """Ctrl+V 到回车之间的等待,只在 paste_and_send 时用。"""


@dataclass
class UIConfig:
    theme: str = "auto"
    """auto / dark / light。"""
    show_overlay: bool = True
    """录音时显示悬浮指示条。关掉就完全静默,但失败时也看不见提示,不建议。"""
    overlay_corner: str = "bottom_right"
    preview_ms: int = 1200
    """识别结果在悬浮条上停留多久。"""

    show_mic_badge: bool = True
    """桌面上常驻一个悬浮麦克风。

    它有两个作用:平时让你知道程序活着,以及**在热键被别的软件占用时
    仍然能用**(实测热键会和微信撞)。点一下开始说话,再点一下结束。
    """
    mic_badge_x: int = -1
    mic_badge_y: int = -1
    """悬浮麦克风的位置。-1 表示还没拖过,用默认位置(右下角偏上)。"""

    badge_action: str = "paste"
    """点悬浮麦克风说完之后做什么:`paste` 只粘贴,`paste_and_send` 粘贴后补一个回车。

    **默认只粘贴**,因为自动回车是不可撤销的 —— 识别错了也已经发出去了。
    对着 Claude Code 连续说话时才值得打开。
    """

    tray_click: str = "open"
    """单击托盘图标做什么:`open` 打开设置窗口,`talk` 开始/结束说话(和点悬浮麦克风一样)。

    给想把入口固定在任务栏上的人用。点托盘会抢焦点,`talk` 模式下会先把焦点
    还给之前那个窗口再录音,见 `focus_tracker.py`。
    """


@dataclass
class HistoryConfig:
    enabled: bool = True
    max_entries: int = 2000
    """超出后删最旧的。历史只是找回错漏用的,不是档案库。"""


@dataclass
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    replacements: dict[str, str] = field(default_factory=dict)
    """术语替换词典。识别结果里的 key 会被换成 value。

    实测 SenseVoice 会把 keytyper 听成 keyper、pytest 听成 P test,
    这类专有名词靠模型解决不了,用词典兜。
    """
    start_minimized: bool = True
    autostart: bool = False

    # ---- 序列化 ----

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        """从 dict 构造,未知键忽略、缺失键用默认值。

        这样旧配置文件遇到新版本不会崩,新配置文件回退到旧版本也不会崩。
        """
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            sub_cls = _SECTION_TYPES.get(f.name)
            if sub_cls is not None:
                if not isinstance(value, dict):
                    continue  # 段被写坏了,用默认值
                kwargs[f.name] = sub_cls(**{
                    sf.name: value[sf.name]
                    for sf in fields(sub_cls)
                    if sf.name in value
                })
            else:
                kwargs[f.name] = value
        return cls(**kwargs)

    def model_path(self) -> Path:
        """模型目录的绝对路径。配置里存相对路径,便于整个目录搬走。"""
        p = Path(self.engine.model_dir)
        return p if p.is_absolute() else app_dir() / p


_SECTION_TYPES: dict[str, type] = {
    "audio": AudioConfig,
    "engine": EngineConfig,
    "hotkey": HotkeyConfig,
    "output": OutputConfig,
    "ui": UIConfig,
    "history": HistoryConfig,
}


# ---- 读写 ----


def load(path: Path | None = None) -> Config:
    """读配置。文件不存在或损坏都回退到默认值,不让用户卡在启动。"""
    path = path or CONFIG_PATH
    if not path.exists():
        return Config()
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return Config()
    try:
        return Config.from_dict(data)
    except (TypeError, ValueError):
        return Config()


def dumps(cfg: Config) -> str:
    """序列化成 TOML 文本。

    自己拼而不用第三方库:配置结构是已知且简单的(标量、字符串表),
    为这点需求引入 tomli-w 不值得。
    """
    lines: list[str] = [
        "# voiceinput 配置文件",
        "# 这个文件可以直接改,也可以在设置界面里改。",
        "",
    ]
    data = cfg.to_dict()

    # 顶层标量先写,否则会被后面的 [section] 吃掉
    for key, value in data.items():
        if isinstance(value, dict) or value is None:
            continue
        lines.append(f"{key} = {_fmt(value)}")
    lines.append("")

    for section, value in data.items():
        if not isinstance(value, dict):
            continue
        if section == "replacements":
            continue  # 放最后,它是变长的
        lines.append(f"[{section}]")
        for key, sub in value.items():
            # TOML 没有 null。写不出来的键直接省略,读回来自然落到默认值,
            # 比写 "" 再想办法解析回 None 干净。
            if sub is None:
                continue
            lines.append(f"{key} = {_fmt(sub)}")
        lines.append("")

    lines.append("# 术语替换:识别结果里的 key 会被整体替换成 value")
    lines.append("[replacements]")
    for key, value in sorted(data.get("replacements", {}).items()):
        lines.append(f"{_fmt(key)} = {_fmt(value)}")
    lines.append("")
    return "\n".join(lines)


def save(cfg: Config, path: Path | None = None) -> None:
    path = path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(cfg), encoding="utf-8")


def _fmt(value: Any) -> str:
    """TOML 字面量。调用方负责先把 None 过滤掉(TOML 没有 null)。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'
