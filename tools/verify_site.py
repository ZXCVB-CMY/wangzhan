"""构建后自检：页面结构、相对链接、RSS、归档。用法： python tools/verify_site.py"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

docs = Path("docs")
data_files = sorted(Path("data").glob("events-*.json"))
if not data_files:
    sys.exit("data/ 里没有事件文件，先跑 run.py")
latest = data_files[-1]
date = latest.stem.replace("events-", "")

html = (docs / "index.html").read_text(encoding="utf-8")
day = (docs / date / "index.html").read_text(encoding="utf-8")
arch = (docs / "archive" / "index.html").read_text(encoding="utf-8")
data = json.loads(latest.read_text(encoding="utf-8"))

print(f"date: {date}")
print("cards on index:", html.count('class="card"'))
print("events in json:", len(data["events"]), "| stats:", data["stats"])
print("overview:", data["overview"][:70])
print("has 今日看点:", "今日看点" in html)
print("has 点评 block:", html.count('class="card-comment"'))
print("tag pills:", html.count('class="tag"'))
print("multi-source line:", html.count("同事件另有"))
print("pending notice:", "本日无数据" in html)

missing = []
pages = sorted(docs.rglob("*.html"))
for page in pages:
    base = page.parent
    for href in re.findall(r'href="([^"]+)"', page.read_text(encoding="utf-8")):
        if href.startswith(("http", "mailto:", "#")):
            continue
        target = (base / href.split("#")[0]).resolve()
        if href.endswith("/"):
            target = target / "index.html"
        if not target.exists():
            missing.append(f"{page.relative_to(docs)}: {href}")
print(f"html pages scanned: {len(pages)}")
print("broken relative links:", missing or "none")

cat_index = (docs / "category" / "index.html").read_text(encoding="utf-8")
cat_rows = cat_index.count('class="cat-row"')
cat_pages = sorted(p for p in (docs / "category").iterdir() if p.is_dir())
print(f"category rows: {cat_rows} | category pages: {len(cat_pages)}")
print("index category chips:", html.count('class="cat-chip"'))
print("tag links on index:", len(re.findall(r'class="tag" href=', html)))
print("header nav (分类/历史):", 'category/' in html and 'archive/' in html)

tree = ET.parse(docs / "feed.xml")
items = tree.getroot().findall("./channel/item")
print("rss items:", len(items))
if items:
    print("  title:", items[0].findtext("title"))
    print("  link :", items[0].findtext("link"))
    print("  date :", items[0].findtext("pubDate"))
    print("  desc :", (items[0].findtext("description") or "").splitlines()[0][:50])

print("archive days listed:", arch.count('class="d-date"'))
m = re.search(r"共\s*\d+\s*天、\d+\s*条事件", arch)
print("archive total:", m.group(0) if m else "?")
print("css size:", (docs / "static" / "style.css").stat().st_size, "bytes")

# 无 JS 检查
print("script tags in html:", html.count("<script"))
print("absolute in-site links in index:", len(re.findall(r'href="/', html)))