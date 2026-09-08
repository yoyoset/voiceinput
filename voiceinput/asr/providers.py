"""问出这台机器上真正能用的推理后端。

**为什么必须探测。** sherpa-onnx 分 CPU 版和 GPU 版两种发行包。
CPU 版拿到 `provider="cuda"` 不会报错,只在 stderr 上打一行:

    Please compile with -DSHERPA_ONNX_ENABLE_GPU=ON.
    Available providers: CPUExecutionProvider, . Fallback to cpu!

然后照常用 CPU 跑完。而 windowed 打包之后根本没有 stderr ——
于是界面上写着 CUDA、配置里存着 cuda、实际跑在 CPU 上,
没有任何地方会告诉用户。这正是这个项目最优先要排除的那种失败。

判据是**发行包里带没带 CUDA 的 provider 动态库**:
带了就是 GPU 版,没带就是 CPU 版。这个判断在任何机器上都成立,
不依赖开发机装了什么显卡。
"""

from __future__ import annotations

import functools
from pathlib import Path

CPU = "cpu"
CUDA = "cuda"

# CUDA 版 sherpa-onnx 会额外带这个。CPU 版的 lib 目录里只有
# onnxruntime + sherpa-onnx 自己的两个库。
_CUDA_MARKERS = ("onnxruntime_providers_cuda.dll", "libonnxruntime_providers_cuda.so")


def _lib_dirs() -> list[Path]:
    try:
        import sherpa_onnx
    except ImportError:
        return []
    root = Path(sherpa_onnx.__file__).resolve().parent
    return [root, root / "lib"]


@functools.lru_cache(maxsize=1)
def available() -> tuple[str, ...]:
    """这台机器上真的能用的 provider。CPU 一定在里面。

    缓存住:装好之后不会中途变化,而这个函数会被界面反复调用。
    """
    for directory in _lib_dirs():
        if not directory.is_dir():
            continue
        for marker in _CUDA_MARKERS:
            if (directory / marker).exists():
                return (CPU, CUDA)
    return (CPU,)


def is_available(provider: str) -> bool:
    return provider.lower() in available()


def resolve(provider: str) -> tuple[str, str]:
    """把配置里的 provider 换成真的能用的那个,并说明改了什么。

    返回 (实际使用的 provider, 给用户看的说明)。说明为空表示没有落差。

    **宁可在这里明说,也不要让 sherpa-onnx 去静默回退。**
    """
    provider = (provider or CPU).lower()
    if is_available(provider):
        return provider, ""
    return CPU, (
        f"这个版本不支持 {provider.upper()},已改用 CPU。"
        "要用显卡得换 GPU 版的 sherpa-onnx。"
    )
