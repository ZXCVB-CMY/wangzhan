"""探针：给一批 URL，看能不能抓、是不是前端渲染、是不是被 WAF 挡。

用法：
    python tools/probe_source.py https://a.com/news https://b.com/list
    python tools/probe_source.py --file urls.txt

只做判断，不改站点代码。判断依据全部打在报告里，方便留着对比。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}

WAF_MARKERS = [
    "slg-bg", "slg-title", "SafeLine", "safeline", "雷池",
    "__jsl_clearance", "acw_sc__v2", "aliyun_waf", "cf-challenge",
    "Just a moment", "attention required",
]
JS_MARKERS = [
    'id="app"', "id='app'", 'id="root"', "__NEXT_DATA__", "window.__NUXT__",
    "__INITIAL_STATE__", "/static/js/", "/assets/index-", "vite",
]
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
A_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def visible_text(html: str) -> str:
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?is)<head>.*?</head>", " ", body)
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", body)).strip()


def title_of(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return SPACE_RE.sub(" ", m.group(1)).strip() if m else ""


def links_of(html: str, base: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for href, inner in A_RE.findall(html):
        text = SPACE_RE.sub(" ", TAG_RE.sub(" ", inner)).strip()
        if len(text) < 8:
            continue
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        out.append((href, text[:90]))
    return out


def probe(url: str) -> dict:
    rec: dict = {"url": url}
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=25) as c:
            r = c.get(url)
        html = r.text or ""
        text = visible_text(html)
        rec.update(
            status=r.status_code,
            final_url=str(r.url),
            ctype=r.headers.get("content-type", ""),
            bytes=len(r.content),
            title=title_of(html),
            text_len=len(text),
            links=len(links_of(html, url)),
        )
        low = html.lower()
        rec["waf"] = [m for m in WAF_MARKERS if m.lower() in low]
        rec["js"] = [m for m in JS_MARKERS if m.lower() in low]
        # 5KB 以上的页面只剩不到 300 字可见文本 = 几乎肯定是前端渲染空壳
        rec["shell"] = rec["bytes"] > 5000 and rec["text_len"] < 300
        rec["html"] = html
    except Exception as e:  # 网络/证书/超时都算探测失败，不中断整批
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec


def report(rec: dict, samples: int = 8) -> None:
    print("=" * 78)
    print(rec["url"])
    if "error" in rec:
        print(f"  ✗ 抓取失败  {rec['error']}")
        return
    print(f"  HTTP {rec['status']}  {rec['bytes']}B  text={rec['text_len']}字  links={rec['links']}")
    if rec["final_url"] != rec["url"]:
        print(f"  跳转 → {rec['final_url']}")
    print(f"  {rec['ctype']}")
    print(f"  title: {rec['title'][:100]}")
    verdict = "可用"
    if rec["waf"]:
        verdict = "WAF 挑战"
    elif rec["shell"]:
        verdict = "前端渲染空壳"
    elif rec["status"] >= 400:
        verdict = "HTTP 错误"
    elif rec["text_len"] < 300:
        verdict = "内容太少"
    print(f"  判定: {verdict}")
    if rec["waf"]:
        print(f"  WAF 特征: {', '.join(rec['waf'][:5])}")
    if rec["js"]:
        print(f"  JS 特征: {', '.join(rec['js'][:5])}")
    if samples:
        print("  链接样本:")
        for href, text in links_of(rec["html"], rec["url"])[:samples]:
            print(f"    - {text[:60]}  ⇒  {href[:90]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--file", help="每行一个 URL 的文件")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--save", help="把每个 URL 的 HTML 存到这个目录，供后面写选择器")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        urls += [ln.strip() for ln in Path(args.file).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not urls:
        ap.print_help()
        return 2

    ok = 0
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}]", end=" ")
        rec = probe(url)
        report(rec, args.samples)
        if rec.get("status", 0) == 200:
            ok += 1
        if args.save and "html" in rec:
            d = Path(args.save)
            d.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^\w.-]+", "_", url.split("://", 1)[-1])[:80] + ".html"
            (d / name).write_text(rec["html"], encoding="utf-8")
    print(f"\n共探测 {len(urls)} 个，HTTP 200 {ok} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())