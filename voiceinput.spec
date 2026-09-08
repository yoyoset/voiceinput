# PyInstaller 打包配置。用 build.py 调用,别直接 pyinstaller voiceinput.spec。
#
# 几个刻意的决定:
#
# - **模型不打进 exe**。模型 237MB,打进去会让 exe 巨大且每次改代码都要重打。
#   放在 exe 旁边的 models/ 里,config.py 的 app_dir() 会正确解析到。
# - **排除大量用不到的 Qt 模块**。PySide6 全量有 1GB 以上,这个程序只用了
#   Widgets/Gui/Core,不排的话打出来的东西没法看。
# - **console=False**:后台常驻程序,不该弹黑框。出问题看 voiceinput.log。

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

# 调试用:VOICEINPUT_CONSOLE=1 打出带控制台的版本,能看到 traceback。
# windowed 版一旦卡在 import 阶段是完全没有输出的,只能靠这个或启动面包屑定位。
CONSOLE = os.environ.get("VOICEINPUT_CONSOLE") == "1"

# sherpa-onnx 的推理靠这些 DLL(尤其是 sherpa-onnx-core 自带的 onnxruntime.dll,
# 缺了会被 C:\Windows\System32 里那个老版本顶包,直接 C++ 层硬退出)
binaries = collect_dynamic_libs("sherpa_onnx")

EXCLUDES = [
    # 一个都用不到,全是几十上百 MB 的大件
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest",
    "PySide6.QtSql", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    # 科学计算全家桶,numpy 用不着它们
    "matplotlib", "scipy", "pandas", "PIL", "tkinter", "IPython",
    "pytest", "setuptools", "pip",
]

a = Analysis(
    # 必须用根目录的 entry.py,不能直接用 voiceinput/__main__.py:
    # PyInstaller 会把入口当顶层脚本跑,包内相对导入会全部失效。
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=[],
    hiddenimports=["sherpa_onnx"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)


# ---- 再砍一遍 Qt 的原生 DLL ----
#
# Analysis 的 excludes 只挡 Python 模块,**挡不住 PySide6 附带的 Qt DLL**——
# 实测排除了 PySide6.QtQuick 之后,Qt6Quick.dll(6.3MB)和 Qt6Qml.dll(5.1MB)
# 照样被打进去。这里按文件名再过滤一次。
#
# 这个程序只用 QtCore / QtGui / QtWidgets,其余的 Qt 模块一个都不需要。

_DROP_QT = (
    "qt6quick", "qt63d", "qt6qml", "qt6quick3d", "qt6quickcontrols",
    "qt6quickparticles", "qt6quickshapes", "qt6quicktest", "qt6quickwidgets",
    "qt6charts", "qt6datavisualization", "qt6graphs",
    "qt6webengine", "qt6webchannel", "qt6websockets", "qt6webview",
    "qt6multimedia", "qt6bluetooth", "qt6nfc", "qt6positioning",
    "qt6location", "qt6sensors", "qt6serialport", "qt6serialbus",
    "qt6designer", "qt6help", "qt6test", "qt6sql", "qt6pdf",
    "qt6opengl", "qt6spatialaudio", "qt6remoteobjects", "qt6scxml",
    "qt6statemachine", "qt6texttospeech", "qt6virtualkeyboard",
    # 软件 OpenGL 兜底实现,19.7MB。纯 QtWidgets 走 raster 画,用不上。
    "opengl32sw",
)


def _keep(entry) -> bool:
    name = Path(entry[0]).name.lower()
    return not any(name.startswith(p) for p in _DROP_QT)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceInput",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,        # 常驻后台程序,正常打包不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VoiceInput",
)
