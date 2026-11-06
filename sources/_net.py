"""抓取层共用的 HTTP 小工具。

只做三件事：带浏览器 UA 请求、失败重试、从 HTML 里抠摘要。
不放业务逻辑——每个站的解析各写各的，坏了一个不影响别的。
"""

from __future__ import annotations

import html
import re
import time

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}

_WS = re.compile(r"[\s\u3000\u00a0]+")
_DESC = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:description|description)[\"'][^>]*content=[\"']([^\"']{10,400})",
    re.I,
)


def get_text(url: str, *, timeout: float = 20.0, retries: int = 2, referer: str = "") -> str:
    """GET 一个页面，失败重试；最终失败就把异常抛给调用方（由 fetch 层记成 error）。"""
    headers = dict(DEFAULT_HEADERS)
    if referer:
        headers["Referer"] = referer
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout) as c:
                r = c.get(url)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001 —— 网络层什么都可能抛，一律重试
            last = e
            if attempt < retries:
                time.sleep(1.0 + attempt)
    raise last  # type: ignore[misc]


def get_html(url: str, **kw) -> str:
    return get_text(url, **kw)


def og_description(page_html: str) -> str:
    """文章页的 meta description，通常就是编辑写的一句话导语。"""
    m = _DESC.search(page_html)
    if not m:
        return ""
    return _WS.sub(" ", html.unescape(m.group(1))).strip()


_NOISE = ("版权", "免责", "扫码", "关注我们", "点击查看", "责任编辑", "声明", "登录后", "APP")
_P = re.compile(r"(?is)<p[^>]*>(.*?)</p>")


def first_paragraphs(page_html: str, max_chars: int = 360, min_len: int = 25) -> str:
    """og:description 缺失时的兜底：把正文里前几个像样的 <p> 拼起来。

    纯启发式，不保证准，但比"原文未提供摘要"强得多。宁短勿错——只拼到 max_chars。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page_html, "html.parser")
    for bad in soup.select("script, style, nav, footer, header, aside"):
        bad.decompose()
    parts: list[str] = []
    total = 0
    for p in soup.find_all("p"):
        text = _WS.sub(" ", p.get_text(" ", strip=True))
        if len(text) < min_len or any(n in text for n in _NOISE):
            continue
        if text in parts:
            continue
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break
    joined = " ".join(parts)
    if len(joined) <= max_chars:
        return joined
    cut = joined[:max_chars]
    pos = max(cut.rfind("。"), cut.rfind("；"))
    return cut[: pos + 1] if pos > 60 else cut.rstrip("，、；") + "…"


def polite_sleep(seconds: float = 0.3) -> None:
    """连续抓文章页时歇一下，别把人家站点打疼。"""
    if seconds > 0:
        time.sleep(seconds)