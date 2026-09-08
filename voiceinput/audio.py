"""音频采集:设备枚举、电平计算、录音。

**设备选择必须交给用户,并且要能看到实时电平当场验证。**
理由是"系统默认输入设备"经常不是话筒:声卡厂商的虚拟设备、
立体声混音、各种 loopback 通道都会占着默认位置,选中了照样能录,
录到的却是系统正在放的声音 —— 表现是"按了热键没反应"或者识别出一堆
莫名其妙的词。

开发机上就是这样(输入设备全是 RØDE Connect 的虚拟通道,默认那个叫
"System Input"),但这不是某个牌子的问题,所以代码里不认牌子:
`looks_like_loopback()` 只按名字给个提示,**唯一可靠的判据仍然是看电平**。
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

log = logging.getLogger("voiceinput")

SAMPLE_RATE = 16000
BLOCK_SIZE = 1024

# 低于这个 RMS 基本可以认为没录到人声。-50 dBFS 是实测拍的经验值。
SILENCE_DBFS = -50.0


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    hostapi: str
    channels: int

    @property
    def label(self) -> str:
        return f"{self.name}  ({self.hostapi})"


def list_devices() -> list[Device]:
    """可用输入设备。同名同 hostapi 去重,只保留 WASAPI 和 MME。

    Windows 上同一个物理设备会在 MME / DirectSound / WASAPI / WDM-KS 四个 hostapi
    下各出现一次,全列出来只会让人选不动。WASAPI 最直接,MME 留着做对照。
    """
    hostapis = sd.query_hostapis()
    seen: set[tuple[str, str]] = set()
    out: list[Device] = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        api = hostapis[dev["hostapi"]]["name"]
        if api not in ("Windows WASAPI", "MME"):
            continue
        key = (dev["name"], api)
        if key in seen:
            continue
        seen.add(key)
        out.append(Device(idx, dev["name"], api, dev["max_input_channels"]))
    return out


# 名字里出现这些词的输入设备,大概率是"系统声音回环"而不是话筒。
#
# **这只是提示,不是判据。** 名字是厂商随便起的,列表永远列不全,
# 而且真话筒也可能撞上这些词。唯一可靠的验证方式是说一句话看电平 ——
# 所以这个函数的输出只用来决定"要不要多提醒一句",不用来禁用任何选项。
_LOOPBACK_WORDS = (
    "system input", "stereo mix", "what u hear", "loopback", "wave out",
    "cable output", "virtual", "voicemeeter", "mix",
    "立体声混音", "混音", "系统声音", "扬声器",
)


def looks_like_loopback(name: str) -> bool:
    """这个设备名看着像系统声音回环吗?"""
    low = name.lower()
    return any(word in low for word in _LOOPBACK_WORDS)


def suspicious_devices(devices: list[Device] | None = None) -> list[Device]:
    """枚举到的设备里,名字看着像回环的那些。"""
    return [d for d in (devices if devices is not None else list_devices())
            if looks_like_loopback(d.name)]


def native_sample_rate(device: int | None) -> int:
    """设备能接受的采样率。

    **不能一律用 16000。** WASAPI 共享模式只接受设备的原生速率,
    请求别的会直接开不了流:

        Error opening InputStream: Invalid sample rate [PaErrorCode -9997]

    本机的 WASAPI 设备原生是 48000 —— 也就是说曾经**选中任何一个 WASAPI 设备
    都录不了音**,而设置界面里一半的选项都是 WASAPI。

    录进来之后按真实速率交给引擎,sherpa-onnx 自己会重采样到 16k,
    实测 16k / 44.1k / 48k 三种输入的识别结果逐字相同。
    (注意:是**如实声明**才对。谎报速率会让识别悄悄变差,见 config.py。)
    """
    try:
        info = sd.query_devices(device, "input")
        rate = int(info["default_samplerate"])
        return rate if rate > 0 else SAMPLE_RATE
    except Exception:
        return SAMPLE_RATE


def resolve_device(index: int | None, name: str = "",
                   hostapi: str = "") -> tuple[int | None, str]:
    """按**名字**找设备编号,编号只作兜底。

    返回 (编号, 说明)。说明非空表示发生了需要告诉用户的事。

    **为什么不能直接用存下来的编号**:PortAudio 的 index 是枚举序号,
    插拔任何一个音频设备都会重排。存 29 号,插个 USB 耳机之后 29 号
    可能已经是别的东西了 —— 于是录音悄悄录错设备,没有任何提示。
    这正是这个项目最想排除的那类失败。
    """
    if not name:
        return index, ""          # 老配置或"系统默认",没有名字可认

    devices = list_devices()
    # 名字 + hostapi 都对上,才是同一个设备
    for d in devices:
        if d.name == name and (not hostapi or d.hostapi == hostapi):
            return d.index, ""
    # 名字对上但 hostapi 变了,退而求其次
    for d in devices:
        if d.name == name:
            return d.index, f"设备「{name}」的接口变成了 {d.hostapi}"

    return None, f"找不到之前选的麦克风「{name}」,已回退到系统默认 —— 请重新选择"


def default_device_index() -> int | None:
    try:
        return sd.default.device[0]
    except Exception:
        return None


def rms_dbfs(audio: np.ndarray) -> float:
    """RMS 电平,dBFS。全静音返回 -inf。"""
    if audio.size == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    if rms <= 1e-9:
        return float("-inf")
    return float(20 * np.log10(rms))


def looks_silent(audio: np.ndarray) -> bool:
    return rms_dbfs(audio) < SILENCE_DBFS


class RecordingError(RuntimeError):
    """麦克风打不开、被占用、设备号失效等。要让用户看见,不能静默失败。"""


def open_stream(device: int | None, sample_rate: int, callback) -> sd.InputStream:
    """打开并启动一条输入流。

    **Recorder 和 LevelMonitor 必须走同一份。** 这两处原来是逐字相同的两段,
    而它们的关系恰恰是"电平表用来验证录音器会不会工作" —— 一旦漂移,
    电平表显示一切正常而录音打不开(或者反过来),那正是这个工具最不能出的错。

    失败一律翻成 `RecordingError`:sounddevice 抛的是 PortAudio 的原始错误,
    直接冒到界面上是一串没人看得懂的东西。
    """
    try:
        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            device=device,
            callback=callback,
        )
        stream.start()
        return stream
    except Exception as e:
        raise RecordingError(f"打不开麦克风: {e}") from e


def close_stream(stream: sd.InputStream | None) -> None:
    """关掉一条流。`None` 当没开过处理。

    **关流失败一概吞掉:** 走到这里都是在收尾,再抛一次只会把真正的原因盖住。
    """
    if stream is None:
        return
    try:
        stream.stop()
        stream.close()
    except Exception as e:
        log.debug("关流失败,忽略: %s", e)


class Recorder:
    """按下开始、松开停止的录音器。

    音频回调跑在 PortAudio 自己的线程上,只做一件事:把 block 塞进队列。
    任何耗时操作都不能放在回调里,否则会丢帧。
    """

    def __init__(self, device: int | None = None, sample_rate: int | None = None,
                 max_seconds: float = 120.0) -> None:
        self._device = device
        # sample_rate=None(默认)表示"用设备的原生速率"。
        # 写死 16000 会让所有 WASAPI 设备开不了流,见 native_sample_rate。
        self._sample_rate = sample_rate or native_sample_rate(device)
        # 用**解析后**的速率算帧数上限。用参数的话 sample_rate=None 时会炸,
        # 而且不同设备速率不同,上限必须跟着走。
        self._max_frames = int(max_seconds * self._sample_rate)
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._frames = 0
        self._overflowed = False
        self._truncated = False

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    @property
    def truncated(self) -> bool:
        """是否因为到达单次上限而丢掉了后面的话。

        必须让上层知道:说了三分钟只转了前两分钟、还什么提示都没有,
        是这个项目最想排除的那类"后台失败但用户以为成功"。
        """
        return self._truncated

    @property
    def overflowed(self) -> bool:
        """PortAudio 是否报过输入溢出(系统忙不过来,采集缓冲被覆盖)。

        溢出意味着**中间有音频真的丢了**,转写结果会缺字漏句,
        但看起来是一句完整的话,用户根本发现不了。
        """
        return self._overflowed

    @property
    def sample_rate(self) -> int:
        """**实际开流用的**采样率,不一定是 16000。

        上层必须拿这个去交给引擎 —— 按 48k 录完却声明 16k,
        识别会悄悄变差(而不是报错)。
        """
        return self._sample_rate

    @property
    def duration_seconds(self) -> float:
        return self._frames / self._sample_rate if self._sample_rate else 0.0

    @property
    def max_seconds(self) -> float:
        return self._max_frames / self._sample_rate if self._sample_rate else 0.0

    def _callback(self, indata, frames, time_info, status) -> None:
        # status 里带着 PortAudio 的 input_overflow 等标志。原来这个参数被整个
        # 忽略掉了,于是丢帧是完全静默的。
        if status and getattr(status, "input_overflow", False):
            self._overflowed = True

        # 按**剩余容量**裁剪,而不是"已录满了才拒绝"。
        # 后者有 off-by-one:第一个块无论多大都会被整块放行,而且如果用户正好
        # 在上限处松手、没有下一个回调,truncated 就永远不会被置上。
        remaining = self._max_frames - self._frames
        if remaining <= 0:
            # 不在这里主动停流:回调跑在 PortAudio 自己的线程上,在里面关流会死锁。
            # 交给上层,但要留下痕迹。
            self._truncated = True
            return

        if frames > remaining:
            self._truncated = True
            self._frames += remaining
            self._queue.put(indata[:remaining].copy())
            return

        self._frames += frames
        self._queue.put(indata.copy())

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._drain()
            self._frames = 0
            self._overflowed = False
            self._truncated = False
            self._stream = open_stream(
                self._device, self._sample_rate, self._callback)

    def stop(self) -> np.ndarray:
        """停止并返回录到的单声道 float32 音频。没录到返回空数组。"""
        with self._lock:
            stream, self._stream = self._stream, None
        close_stream(stream)

        parts: list[np.ndarray] = []
        while True:
            try:
                parts.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not parts:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(parts, axis=0)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio.astype(np.float32, copy=False)

    def peek_level(self) -> float:
        """当前电平,给悬浮条画音量用。不消费队列里的数据。"""
        try:
            block = self._queue.queue[-1]
        except IndexError:
            return float("-inf")
        return rms_dbfs(np.asarray(block).ravel())

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


class LevelMonitor:
    """设置界面用的实时电平表。独立于 Recorder,只为"选对设备"服务。"""

    def __init__(self, device: int | None = None, sample_rate: int | None = None) -> None:
        self._device = device
        # 同 Recorder:写死 16000 会让 WASAPI 设备直接开不了流
        self._sample_rate = sample_rate or native_sample_rate(device)
        self._stream: sd.InputStream | None = None
        self._level = float("-inf")

    @property
    def level_dbfs(self) -> float:
        return self._level

    def _callback(self, indata, frames, time_info, status) -> None:
        self._level = rms_dbfs(np.asarray(indata).ravel())

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stream = open_stream(self._device, self._sample_rate, self._callback)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        self._level = float("-inf")
        close_stream(stream)
