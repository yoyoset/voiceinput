"""设置窗口的各个分页。

拆开的判据是**"谁在改这个状态"**:每个分页拥有自己的控件,
自己知道怎么把它们写回 Config。窗口不认识任何一个具体控件。
"""

from .about import AboutPage
from .audio import AudioPage
from .base import Page
from .dictionary import DictionaryPage
from .engine import EnginePage
from .general import GeneralPage
from .history import HistoryPage

__all__ = [
    "Page",
    "GeneralPage",
    "AudioPage",
    "EnginePage",
    "DictionaryPage",
    "HistoryPage",
    "AboutPage",
]
