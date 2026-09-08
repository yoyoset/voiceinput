"""所有测试共用的准备工作。

原来这三样东西被复制在每个测试文件的顶部:`sys.path` 补丁(34 份)、
`QT_QPA_PLATFORM=offscreen`(21 份)、`qapp` fixture(19 份,其中 18 份逐字相同)。

**当时并没有漏网的 —— 但第 36 个测试文件就是会忘的那个。** 而忘掉
`QT_QPA_PLATFORM` 的后果尤其难查:它是在 import 时生效的,所以"漏了也能过"
完全取决于 pytest 的收集顺序;等到某天单独跑那一个文件,才会突然弹出真窗口。
"""

import os
import sys
from pathlib import Path

import pytest

# 必须在任何 PySide6 导入之前。放在 conftest 里能保证这一点 ——
# pytest 总是先加载 conftest,再收集测试文件。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def qapp():
    """整个测试会话共用一个 QApplication。

    **不能每个测试建一个** —— Qt 不支持在一个进程里反复创建销毁
    QApplication,第二次会直接崩。
    """
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])
