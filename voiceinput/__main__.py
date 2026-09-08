"""支持 `python -m voiceinput`。

用绝对导入,不用 `from .cli import main`:`python -m` 下两者都行,
但保持和 entry.py 一致更不容易再踩到相对导入的坑。
"""

import sys

from voiceinput.cli import main

if __name__ == "__main__":
    sys.exit(main())
