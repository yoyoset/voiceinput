"""PyInstaller 的入口脚本。

必须是**项目根下的顶层脚本 + 绝对导入**。直接拿 `voiceinput/__main__.py` 当入口
会让 PyInstaller 以顶层脚本方式执行它,`__package__` 为空,包内的相对导入
全部报 ImportError,exe 起不来。详见 voiceinput/cli.py 的说明。
"""

import sys

from voiceinput.cli import main

if __name__ == "__main__":
    sys.exit(main())
