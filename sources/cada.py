"""中国汽车流通协会（cada.cn）。

为什么选它：协会口径的周度数据（车市扫描、库存预警指数、月度深度分析）是"官方视角"，
量不大但分量重，而且站点是普通 CMS，没有反爬。

已知情况（2026-11-06 实测）：
- 列表页形如 ``/Trends/list_91_1.html``，条目是 ``div.neirong``（标题 + ``div.shijian`` 时间）。
- 更新频率是周级，多数日子在 48 小时窗口里是 0 条，属于"有就赚到"的源，不能当主力。
- ``/Data`` 栏目更慢（月度），一起抓，反正一次请求的事。
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from . import _net
from .base import CN_TZ, RawItem, SourceNotReady, iso

SOURCE = {
    "id": "cada",
    "label": "中国汽车流通协会",
    "home": "https://www.cada.cn/",
}

BASE = "https://www.cada.cn"
LIST_PAGES = [
    "/Trends/list_91_1.html",   # 协会快讯 / 车市扫描
    "/Trends/list_92_1.html",   # 行业资讯
    "/Data/list_85_1.html",     # 数据 / 库存预警
]
MAX_ENRICH = 6
LEAD_CHARS = 240
_INFO = re.compile(r"/(Trends|Data|liebiao)/info_\d+_\d+\.html$")


def _lead(page_html: str) -> str:
    """正文首段。这个站的 meta description 是站点关键词堆，没有信息量，只能取正文。"""
    soup = BeautifulSoup(page_html, "html.parser")
    box = soup.select_one("div.jieshao") or soup.select_one("div.content")
    if not box:
        return _net.og_description(page_html)
    text = box.get_text(" ", strip=True)
    if len(text) <= LEAD_CHARS:
        return text
    cut = max(text.rfind("。", 0, LEAD_CHARS), text.rfind("；", 0, LEAD_CHARS))
    return text[: cut + 1] if cut > 60 else text[:LEAD_CHARS]


def _parse_time(raw: str) -> str:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return iso(datetime.strptime(raw, fmt).replace(tzinfo=CN_TZ))
        except ValueError:
            continue
    return ""


def fetch(limit: int = 30) -> list[RawItem]:
    seen: dict[str, RawItem] = {}
    errors: list[str] = []
    for path in LIST_PAGES:
        try:
            page = _net.get_html(BASE + path)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{path}: {type(e).__name__}: {e}")
            continue
        soup = BeautifulSoup(page, "html.parser")
        for block in soup.select("div.neirong"):
            a = block.find("a", href=True)
            if not a:
                continue
            href = a["href"].strip()
            if not _INFO.search(href):
                continue
            title = a.get_text(" ", strip=True)
            if len(title) < 6:
                continue
            url = href if href.startswith("http") else BASE + href
            when = block.select_one("div.shijian")
            seen.setdefault(
                url,
                RawItem(
                    title=title,
                    url=url,
                    source_id=SOURCE["id"],
                    source_label=SOURCE["label"],
                    published_at=_parse_time(when.get_text(" ", strip=True) if when else ""),
                    extra={"list_page": path},
                ),
            )

    if not seen:
        if errors:
            raise RuntimeError("中国汽车流通协会列表页抓取失败：" + "; ".join(errors[:3]))
        raise SourceNotReady("中国汽车流通协会列表页没解析出条目")

    items = sorted(seen.values(), key=lambda i: i.published_at, reverse=True)[:limit]
    for it in items[:MAX_ENRICH]:
        try:
            it.summary_raw = _lead(_net.get_html(it.url))
        except Exception:  # noqa: BLE001
            it.summary_raw = ""
        _net.polite_sleep(0.3)
    return items