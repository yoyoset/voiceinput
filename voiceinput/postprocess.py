"""识别结果的文本后处理。全是纯函数,不碰 IO,可独立单测。

每条规则都对应一个实测观察到的问题,不是凭空想的:

- SenseVoice 输出 `把这个 function改成async` —— ASCII 段前后空格时有时无
- SenseVoice 把 keytyper 听成 keyper、pytest 听成 "P test" —— 专有名词靠词典兜
- 偶尔会在结果里留下 `<|zh|><|NEUTRAL|>` 这类特殊标记
"""

from __future__ import annotations

import re

# SenseVoice 的语种/情感/事件标记,形如 <|zh|> <|NEUTRAL|> <|Speech|> <|woitn|>
_TAG_RE = re.compile(r"<\|[^|>]*\|>")

# 连续的 ASCII 段(英文单词、数字、标识符),用来判断哪里该加空格。
#
# 必须**以字母数字开头和结尾**:否则单独一个 `.` 也会被当成"英文词",
# 于是 `你好.` 被拆成 `你好 .`。中间允许 . / _ - + # 是为了让
# `config.toml`、`large-v3` 这类标识符不被拆开。
_ASCII_RUN = r"[A-Za-z0-9](?:[A-Za-z0-9_./+\-#]*[A-Za-z0-9])?"

# CJK 字符(中日韩)
_CJK = r"[一-鿿぀-ヿ가-힯]"

_CJK_THEN_ASCII = re.compile(rf"({_CJK})({_ASCII_RUN})")
_ASCII_THEN_CJK = re.compile(rf"({_ASCII_RUN})({_CJK})")

# 中文标点后面不该再跟空格
_SPACE_AFTER_CJK_PUNCT = re.compile(r"([，。、；：？！）】》」』])\s+")
# 中文标点前面不该有空格
_SPACE_BEFORE_CJK_PUNCT = re.compile(r"\s+([，。、；：？！）】》」』])")


def strip_tags(text: str) -> str:
    """去掉 SenseVoice 的 <|...|> 标记。"""
    return _TAG_RE.sub("", text)


def collapse_whitespace(text: str) -> str:
    """多个空白折成一个,首尾去掉。换行也算空白——语音输入不该产生换行。"""
    return re.sub(r"\s+", " ", text).strip()


def fix_cjk_ascii_spacing(text: str) -> str:
    """中英之间统一加一个空格。

    识别结果里 `把这个 function改成async` 这种半有半无的空格看着很业余,
    统一成 `把这个 function 改成 async`。
    """
    text = _CJK_THEN_ASCII.sub(r"\1 \2", text)
    text = _ASCII_THEN_CJK.sub(r"\1 \2", text)
    return text


def fix_punct_spacing(text: str) -> str:
    """中文标点周围不留空格。上一步加空格时可能会误伤到标点旁边。"""
    text = _SPACE_BEFORE_CJK_PUNCT.sub(r"\1", text)
    text = _SPACE_AFTER_CJK_PUNCT.sub(r"\1", text)
    return text


def apply_replacements(text: str, replacements: dict[str, str]) -> str:
    """按词典做整体替换。大小写不敏感,替换成词典里写的形式
    (识别结果的大小写本来就不可靠)。

    **单遍扫描,替换结果不再参与后续匹配。** 挨个 `re.sub` 会级联出错:
    词典同时有 `P test -> pytest` 和 `test -> TEST` 时,前者先替换出 "pytest",
    后者又在这个结果里匹配到 "test",最终变成 "pyTEST"。
    把所有 key 拼成一个正则做一次替换就不会。

    key 按长度降序进入正则,保证 `P test` 优先于 `test` 被匹配上。
    """
    if not replacements:
        return text
    keys = [k for k in sorted(replacements, key=len, reverse=True) if k]
    if not keys:
        return text

    # 同一个 key 大小写不同的写法会撞到一起,长的先来,先到先得
    lookup: dict[str, str] = {}
    for k in keys:
        lookup.setdefault(k.lower(), replacements[k])

    pattern = re.compile("|".join(re.escape(k) for k in keys), re.IGNORECASE)
    return pattern.sub(lambda m: lookup[m.group(0).lower()], text)


def clean(text: str, replacements: dict[str, str] | None = None) -> str:
    """完整后处理链。顺序有讲究:

    先去标记,再替换术语(此时空格还是模型原样,词典按原样写更直觉),
    最后统一空格和标点。
    """
    text = strip_tags(text)
    text = collapse_whitespace(text)
    text = apply_replacements(text, replacements or {})
    text = fix_cjk_ascii_spacing(text)
    text = fix_punct_spacing(text)
    return collapse_whitespace(text)


def is_effectively_empty(text: str) -> bool:
    """判断识别结果是不是等于什么都没说。

    没录到人声时模型可能吐出空串、纯标点或残留标记,
    这些都不该往光标处粘贴——粘一堆标点比什么都不做更烦人。
    """
    stripped = strip_tags(text)
    return not any(ch.isalnum() for ch in stripped)


NOTHING_RECOGNISED = "没有识别到内容"


def finalize(raw: str, replacements: dict[str, str] | None = None) -> tuple[str, str]:
    """原始识别结果 → (可以粘的文字, 失败原因)。两者必有一个是空串。

    **两道关都要过,而且都算"没有识别到内容"。** 第一道拦模型在静音上
    吐出来的纯标点/残留标记;第二道拦词典把整句话替换成空的情况
    (词条的目标写成空是合法的,意思就是"这个词删掉")。

    调用方原来自己写两遍判断加同一句失败文案 —— 那种写法迟早会
    只改其中一处,于是同一件事出现两种说法。
    """
    if is_effectively_empty(raw):
        return "", NOTHING_RECOGNISED
    text = clean(raw, replacements)
    if not text:
        return "", NOTHING_RECOGNISED
    return text, ""
