"""新浪汽车·行业新闻（auto.sina.com.cn/news/）。

为什么选它：老牌门户，行业稿是服务端渲染，列表页直接带导语（p.intro）和精确到秒的时间，
不需要再抓文章页。缺点是更新不快——一页 15 条大概覆盖三四天，属于"补主流视角"的源。

已知情况（2026-11-06 实测）：
- 列表页带分页链接 ``?page=N``，但带不带参数返回的都是同一批 15 条，实际上不能翻页。
- 侧栏"推荐阅读"混在同一块里，所以只认 ``h3 > a`` 的主稿，避免把推荐位当新闻。
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import _net
from .base import CN_TZ, RawItem, SourceNotReady, iso

SOURCE = {
    "id": "sina",
    "label": "新浪汽车",
    "home": "https://auto.sina.com.cn/news/",
}

LIST_URL = "https://auto.sina.com.cn/news/"
MAX_ENRICH = 6  # 列表页导语是「查看全文 >>」的，最多回源补几篇正文导语
_TAIL = re.compile(r"(查看全文|阅读全文|详情)\s*[>＞»]*\s*$")
_PUNCT = re.compile(r"[\s>＞»…\.．,，。、]+$")


def _clean_intro(text: str) -> str:
    """列表页的 p.intro 有时只是「查看全文 >>」这种占位符，不能当导语用。"""
    t = _TAIL.sub("", text or "").strip()
    t = _PUNCT.sub("", t)
    return t if len(t) >= 12 else ""


def _parse_time(raw: str) -> str:
    raw = (raw or "").strip()
    try:
        from datetime import datetime

        return iso(datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ))
    except ValueError:
        return raw


def _abs_url(href: str) -> str:
    href = (href or "").strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://auto.sina.com.cn" + href
    return href


def fetch(limit: int = 30) -> list[RawItem]:
    page = _net.get_html(LIST_URL)
    soup = BeautifulSoup(page, "html.parser")
    out: list[RawItem] = []
    seen: set[str] = set()

    for block in soup.select("div.single"):
        a = block.select_one("h3 a")
        if not a or not a.get("href"):
            continue
        url = _abs_url(a["href"])
        if not url or url in seen:
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        intro = block.select_one("p.intro")
        summary = _clean_intro(intro.get_text(" ", strip=True)) if intro else ""
        time_el = block.select_one("span.time")
        seen.add(url)
        out.append(
            RawItem(
                title=title,
                url=url,
                source_id=SOURCE["id"],
                source_label=SOURCE["label"],
                published_at=_parse_time(time_el.get_text(strip=True) if time_el else ""),
                summary_raw=summary,
            )
        )
        if len(out) >= limit:
            break

    if not out:
        raise SourceNotReady("新浪汽车列表页没解析出条目，页面结构可能变了")

    # 列表页有一部分条目的 p.intro 只是「查看全文 >>」，只靠标题 LLM 只能复述标题，
    # 所以少量回源抓正文首段（每篇 200 字左右），够摘要用。
    missing = [item for item in out if not item.summary_raw][:MAX_ENRICH]
    for item in missing:
        try:
            html = _net.get_text(item.url)
            text = _net.og_description(html) or _net.first_paragraphs(html, max_chars=300)
            item.summary_raw = text
        except Exception:  # noqa: BLE001 —— 补不到就算了，不能因此丢条目
            continue
        finally:
            _net.polite_sleep(0.4)

    return out