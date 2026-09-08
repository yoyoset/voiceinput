"""CER 计算与文本归一化。纯函数,无外部依赖,可独立单测。

CER 报两个口径:
  - raw:原样比对,标点/大小写都算数
  - norm:去掉标点和空白、英文转小写后比对

两个都要看:norm 反映"意思对不对",raw 反映"能不能直接用而不用手改标点"。
对语音输入工具来说 raw 其实更贴近真实体验——标点错了你还是得动手。
"""

import re
import unicodedata

# 中英文标点。不用 string.punctuation,那个漏掉全角。
_PUNCT_EXTRA = "，。、；：？！“”‘’（）《》【】—…·「」『』～"


def is_punct(ch: str) -> bool:
    """标点或符号。"""
    if ch in _PUNCT_EXTRA:
        return True
    return unicodedata.category(ch).startswith(("P", "S"))


_CN_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10_000, "亿": 100_000_000}
_CN_NUM_RE = re.compile(f"[{''.join(_CN_DIGITS)}{''.join(_CN_UNITS)}]+")


def _cn_chunk_to_int(chunk: str) -> int | None:
    """把一段中文数字转成整数。转不了返回 None。"""
    total = section = 0
    seen = False
    for ch in chunk:
        if ch in _CN_DIGITS:
            section = _CN_DIGITS[ch]
            seen = True
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit >= 10_000:
                total = (total + max(section, 1)) * unit
                section = 0
            else:
                section = max(section, 1) * unit
                total += section
                section = 0
            seen = True
        else:
            return None
    return total + section if seen else None


def numbers_to_arabic(text: str) -> str:
    """中文数字转阿拉伯数字。

    **为什么 CER 需要这个**:开了 ITN 之后模型输出的是「30秒」,
    而朗读稿写的是「三十秒」—— 内容完全正确,逐字比却会算出大面积错误。
    实测一条含数字的句子被判成 30.4% CER,而它一个字都没错。
    不修的话,含数字的样本会把引擎的成绩压得莫名其妙地低。

    转换不必完美:**两边用同一套转换**,转不准也只是"没修好真错误",
    不会凭空造出假错误。
    """
    def repl(m: re.Match) -> str:
        value = _cn_chunk_to_int(m.group(0))
        return str(value) if value is not None else m.group(0)

    return _CN_NUM_RE.sub(repl, text)


def normalize(text: str) -> str:
    """归一化:全角转半角、中文数字转阿拉伯、去标点、去空白、英文小写。"""
    text = unicodedata.normalize("NFKC", text)
    text = numbers_to_arabic(text)
    return "".join(ch.lower() for ch in text if not ch.isspace() and not is_punct(ch))


def edit_distance(a: str, b: str) -> int:
    """Levenshtein 距离。滚动数组,只留两行。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,          # 删除
                cur[j - 1] + 1,       # 插入
                prev[j - 1] + (ca != cb),  # 替换
            ))
        prev = cur
    return prev[-1]


def cer(truth: str, hyp: str) -> float:
    """字错误率。truth 为空时:hyp 也空算 0,否则算 1。"""
    if not truth:
        return 0.0 if not hyp else 1.0
    return edit_distance(truth, hyp) / len(truth)


def score(truth: str, hyp: str) -> dict[str, float]:
    """一次算出 raw 和 norm 两个口径。"""
    return {
        "cer_raw": cer(truth, hyp),
        "cer_norm": cer(normalize(truth), normalize(hyp)),
    }
