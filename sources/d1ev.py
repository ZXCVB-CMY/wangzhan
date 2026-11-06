"""第一电动网（d1ev.com）。

为什么选它：列表页是服务端渲染的静态 HTML，没有登录墙、没有 WAF 挑战，
栏目分得细（市场/企业/数据/政策/技术/评论/资本），新能源这条线的日更量足够。

已知情况（2026-11-06 实测）：
- 列表页每页 20 条，``?page=2`` 之类的翻页参数会被忽略，拿到的永远是首页那 20 条。
  所以靠多栏目并集凑量，不靠翻页。
- 列表页本身没有导语，只有标题/作者/时间。摘要靠抓文章页的 meta description 补，
  只对最近 3 天的前 18 条做，避免一次请求几十个页面。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from . import _net
from .base import CN_TZ, RawItem, SourceNotReady, iso, now_cn

SOURCE = {
    "id": "d1ev",
    "label": "第一电动网",
    "home": "https://www.d1ev.com/news",
}

BASE = "https://www.d1ev.com"
PAGES = [
    "/news",
    "/news/shichang",
    "/news/qiye",
    "/news/shuju",
    "/news/zhengce",
    "/news/jishu",
    "/news/pinglun",
    "/news/ziben",
]
MAX_ENRICH = 32          # 最多补多少条导语（约 30 次请求，一次构建多花半分钟）
ENRICH_WINDOW_HOURS = 48  # 只补 48 小时内会展示的，更早的补了也用不上


def _parse_time(raw: str) -> str:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return iso(datetime.strptime(raw, fmt).replace(tzinfo=CN_TZ))
        except ValueError:
            continue
    return ""


def _items_from_page(page: str, page_url: str) -> list[RawItem]:
    soup = BeautifulSoup(page, "html.parser")
    out: list[RawItem] = []
    for block in soup.select("div.article--wraped"):
        a = block.select_one("span.article_p a")
        if not a or not a.get("href"):
            continue
        href = a["href"].strip()
        if not href.startswith("/news/"):
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        time_el = block.select_one("time.timeago")
        img = block.select_one("div.article--img img")
        tip = block.select_one("div.article--img .tip")
        out.append(
            RawItem(
                title=title,
                url=BASE + href,
                source_id=SOURCE["id"],
                source_label=SOURCE["label"],
                published_at=_parse_time(time_el.get("datetime", "") if time_el else ""),
                cover=(img.get("src") or "").strip() if img else "",
                extra={"channel": tip.get_text(strip=True) if tip else "", "list_page": page_url},
            )
        )
    return out


def fetch(limit: int = 30) -> list[RawItem]:
    seen: dict[str, RawItem] = {}
    errors: list[str] = []
    for path in PAGES:
        page_url = BASE + path
        try:
            page = _net.get_html(page_url)
        except Exception as e:  # noqa: BLE001 —— 单个栏目挂了不影响别的
            errors.append(f"{path}: {type(e).__name__}: {e}")
            continue
        for it in _items_from_page(page, page_url):
            seen.setdefault(it.url, it)

    if not seen:
        if errors:
            raise RuntimeError("第一电动网所有栏目都抓取失败：" + "; ".join(errors[:3]))
        raise SourceNotReady("第一电动网列表页解析为空，页面结构可能变了")

    items = sorted(seen.values(), key=lambda i: i.published_at, reverse=True)[:limit]

    cutoff = now_cn() - timedelta(hours=ENRICH_WINDOW_HOURS)
    enriched = 0
    for it in items:
        if enriched >= MAX_ENRICH:
            break
        try:
            when = datetime.fromisoformat(it.published_at) if it.published_at else None
        except ValueError:
            when = None
        if when is not None and when < cutoff:
            continue
        try:
            page = _net.get_html(it.url)
            it.summary_raw = _net.og_description(page) or _net.first_paragraphs(page)
        except Exception:  # noqa: BLE001 —— 补不上就空着，LLM 还能靠标题写
            it.summary_raw = ""
        enriched += 1
        _net.polite_sleep(0.3)

    return items