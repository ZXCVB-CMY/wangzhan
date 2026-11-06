"""去重：URL 硬去重 + 文本二元组 Dice 软去重。

中文没有空格，用字符二元组（bigram）集合算 Dice 系数，不装分词器、不建倒排：
    同一条稿子被两家转载    ≈ 0.90–1.00
    同一事件、标题重写      ≈ 0.45–0.80
    完全无关的两条稿子      < 0.35
（16 条汽车行业样例实测：同稿 0.98、改写 0.70、无关最高 0.35。）

为什么不用 SimHash：在短中文标题上，SimHash 对无关文本的基线漂在 0.5–0.6，
和"同一事件"的 0.6–0.8 挤在一起，阈值怎么调都要么漏合要么错合。Dice 的分离度明显更好。
数据量是每天几十条，O(n²) 比较完全够用。
"""

from __future__ import annotations

import re

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_TOKEN = re.compile(r"[a-z0-9]+(?:[.．][0-9]+)?")  # 数字带上小数点：51.2、58.7 是强特征
_STRIP = re.compile(r"[^\u4e00-\u9fffa-z0-9.]+")


def bigrams(text: str) -> set[str]:
    """标题/正文 → 特征集合：中文二元组 + 英文数字词。"""
    text = (text or "").lower()
    feats: set[str] = set()
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            feats.add(run)
        else:
            feats.update(run[i : i + 2] for i in range(len(run) - 1))
    feats.update(_TOKEN.findall(text))
    return feats or {_STRIP.sub("", text) or "empty"}


def dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def similarity(a: dict, b: dict) -> float:
    """两条数据（标题必填、摘要可选）的相似度：标题占 6 成，摘要占 4 成。"""
    t = dice(bigrams(a.get("title", "")), bigrams(b.get("title", "")))
    sa, sb = a.get("summary_raw") or a.get("summary") or "", b.get("summary_raw") or b.get("summary") or ""
    if not sa or not sb:
        return t
    s = dice(bigrams(sa), bigrams(sb))
    return round(0.6 * t + 0.4 * s, 4)


def dedupe(items: list[dict], threshold: float = 0.9) -> tuple[list[dict], int]:
    """items 需按发布时间倒序传入：重复时保留更新的那条。返回 (保留项, 丢弃数)。"""
    kept: list[dict] = []
    seen_urls: set[str] = set()
    dropped = 0

    for item in items:
        if item["url"] in seen_urls:
            dropped += 1
            continue
        if any(similarity(item, prev) >= threshold for prev in kept):
            dropped += 1
            continue
        seen_urls.add(item["url"])
        kept.append(item)
    return kept, dropped