"""打包成便携版(绿色软件)。

产物:dist/VoiceInput/ 整个目录,里面是 VoiceInput.exe + 依赖 + models/。
拷走整个目录就能在别的机器上跑,不需要安装、不写注册表。

用法:
    uv run --group dev python build.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "VoiceInput"
MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# 用户的东西,不是产物。绿色软件把数据放在 exe 旁边,而打包要 rmtree 整个 dist,
# 于是"重新打包"顺手就把用户的设置和历史删了。
USER_DATA = ("config.toml", "history.db", "voiceinput.log")


def rescue_user_data(dist: Path) -> Path | None:
    """把用户数据挪到 dist 之外,返回备份目录(没有可救的就返回 None)。

    **这是被真实事故逼出来的。** 2026-08-26 这天重新打包,
    `clean_dist()` 的 rmtree 把用户的 config.toml 和 history.db
    一起删了 —— 没有提示、没有备份、不可恢复。

    在那之前"记得先手工备份"是靠人记住的,于是有一次就没记住。
    **靠记性的步骤等于没有这个步骤**,所以改成打包流程自己做。
    """
    found = [name for name in USER_DATA if (dist / name).is_file()]
    if not found:
        return None
    backup = Path(tempfile.mkdtemp(prefix="voiceinput-userdata-"))
    for name in found:
        shutil.copy2(dist / name, backup / name)
    print(f"已备份用户数据({', '.join(found)})→ {backup}")
    return backup


def restore_user_data(backup: Path | None, dist: Path) -> None:
    """把备份放回新产物里。

    **不覆盖已存在的同名文件**:走到这一步产物是全新的,不该有同名文件;
    真有的话说明打包过程自己生成了一份,那更该保留用户的还是新的
    是个需要人来判断的问题,不该由脚本静默决定。
    """
    if backup is None:
        return
    dist.mkdir(parents=True, exist_ok=True)
    restored = []
    for src in sorted(backup.iterdir()):
        dst = dist / src.name
        if dst.exists():
            print(f"! {src.name} 在新产物里已存在,没有覆盖。备份仍在 {backup}")
            continue
        shutil.copy2(src, dst)
        restored.append(src.name)
    if restored:
        print(f"已还原用户数据:{', '.join(restored)}")
    shutil.rmtree(backup, ignore_errors=True)


def clean_dist() -> bool:
    """删掉旧的 dist。删不掉时给出人话原因,不要甩一坨 traceback。

    这个坑踩过:程序还开着、或者某个 shell 的当前目录停在 dist/VoiceInput 里,
    Windows 就不让删,报的是 WinError 32。光看 traceback 想不到是"某个终端
    还 cd 在里面"。
    """
    dist = ROOT / "dist"
    if not dist.exists():
        return True
    try:
        shutil.rmtree(dist)
        return True
    except PermissionError as e:
        print()
        print(f"删不掉 {dist}:{e.strerror or e}")
        print("常见原因:")
        print("  1. VoiceInput.exe 还在运行(托盘里退出它)")
        print("  2. 有终端的当前目录停在 dist/VoiceInput 里(cd 出来)")
        print("  3. 资源管理器正开着这个目录")
        return False
    except OSError as e:
        print(f"删不掉 {dist}: {e}")
        return False


def main() -> int:
    src_model = ROOT / "models" / MODEL_NAME
    if not (src_model / "model.int8.onnx").exists():
        print(f"缺少模型: {src_model}")
        print("先下载模型再打包,否则产物开箱不可用。")
        return 1

    print("清理旧产物…")
    backup = rescue_user_data(DIST)     # 必须在 clean_dist 之前
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    if not clean_dist():
        if backup is not None:
            print(f"没有删除任何东西,用户数据备份留在 {backup}")
        return 1

    print("PyInstaller 打包中(会跑几分钟)…")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "voiceinput.spec"],
        cwd=ROOT,
    )
    if result.returncode != 0:
        print("打包失败")
        # 旧产物已经删了,备份是用户数据仅存的一份 —— 必须说清楚它在哪
        if backup is not None:
            print(f"用户数据备份留在 {backup}")
        return result.returncode

    exe = DIST / "VoiceInput.exe"
    if not exe.exists():
        print(f"没找到产物: {exe}")
        if backup is not None:
            print(f"用户数据备份留在 {backup}")
        return 1

    restore_user_data(backup, DIST)

    # 模型不进 exe(237MB,而且改代码不该重打模型),拷到 exe 旁边。
    # config.py 里 app_dir() 在 frozen 情况下返回 exe 所在目录,相对路径能对上。
    print("拷贝模型…")
    dst_model = DIST / "models" / MODEL_NAME
    dst_model.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_model, dst_model, dirs_exist_ok=True)
    # test_wavs 是模型自带的示例音频,发布时没用
    shutil.rmtree(dst_model / "test_wavs", ignore_errors=True)

    print()
    print("=" * 56)
    print(f"产物:   {DIST}")
    print(f"可执行: {exe.name}  ({human(exe.stat().st_size)})")
    print(f"总大小: {human(dir_size(DIST))}")
    print("=" * 56)
    print("整个 VoiceInput 目录拷走即可使用,配置和历史会生成在同一目录下。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
