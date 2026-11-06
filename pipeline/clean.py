"""清洗：把抓取层给的脏数据洗成统一字段。

只做确定性的事——去标签、归一空白、统一时间、修 URL。
判断"要不要"的活留给 rank，判断"是不是同一条"的活留给 dedupe。
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[\s\u3000\u00a0]+")
_TRACKING = re.compile(r"^(utm_|spm|from|share_|_ga|ref)", re.I)


def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    return _WS.sub(" ", s).strip()


def normalize_url(url: str) -> str:
    """去掉跟踪参数、锚点，统一小写主机名。"""
    if not url:
        return ""
    url = url.strip()
    try:
        p = urlsplit(url)
    except ValueError:
        return url
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    query.sort()
    path = p.path or "/"
    return urlunsplit((p.scheme or "https", p.netloc.lower(), path, urlencode(query), ""))


def parse_time(value: str) -> datetime | None:
    """尽量把各种写法读成北京时间 aware datetime，读不出来返回 None。"""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
        return dt if dt.tzinfo else dt.replace(tzinfo=CN_TZ)

    s = str(value).strip().replace("/", "-").replace("年", "-").replace("月", "-").replace("日", " ")
    s = s.replace("T", " ").replace("Z", "+00:00")
    s = _WS.sub(" ", s)

    # 纯时间戳
    if re.fullmatch(r"\d{10}", s):
        return datetime.fromtimestamp(int(s), CN_TZ)
    if re.fullmatch(r"\d{13}", s):
        return datetime.fromtimestamp(int(s) / 1000, CN_TZ)

    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if fmt == "%m-%d %H:%M":
            now = datetime.now(CN_TZ)
            dt = dt.replace(year=now.year)
            if dt > now + timedelta(days=1):
                dt = dt.replace(year=now.year - 1)
        return dt if dt.tzinfo else dt.replace(tzinfo=CN_TZ)

    # 兜底：正则抠
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ ](\d{1,2}):(\d{2}))?", s)
    if m:
        y, mo, d, hh, mm = (int(x) if x else 0 for x in m.groups())
        return datetime(y, mo, d, hh, mm, tzinfo=CN_TZ)
    return None


def clean_item(raw: dict, now: datetime) -> dict | None:
    title = strip_html(raw.get("title", ""))
    url = normalize_url(raw.get("url", ""))
    if not title or not url:
        return None
    if len(title) < 6:  # 导航残留、栏目名之类
        return None

    published = parse_time(raw.get("published_at", ""))
    if published is None:
        published = now
    if published > now + timedelta(hours=2):  # 明显是未来时间，视为脏数据
        published = now

    summary = strip_html(raw.get("summary_raw", ""))
    if summary and summary in title:
        summary = ""

    return {
        "title": title,
        "url": url,
        "source_id": raw.get("source_id", ""),
        "source_label": raw.get("source_label", ""),
        "published_at": published,
        "summary_raw": summary,
        "cover": (raw.get("cover") or "").strip(),
        "tags": [t.strip() for t in (raw.get("tags") or []) if t and t.strip()],
    }


def clean_all(items: list[dict], now: datetime) -> list[dict]:
    out, seen = [], set()
    for raw in items:
        item = clean_item(raw, now)
        if item is None:
            continue
        key = (item["url"], item["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out