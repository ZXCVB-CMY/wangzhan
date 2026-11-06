"""渲染层：把事件渲染成纯静态站点。

产物（docs/ 就是 Pages 的根目录）：
  docs/index.html            今日
  docs/<YYYY-MM-DD>/index.html  单日页（固定链接）
  docs/archive/index.html    历史（按月分组，含每日头条）
  docs/category/index.html   全部分类
  docs/category/<slug>/index.html  单个分类的历史事件
  docs/feed.xml              RSS，每天一条
  docs/static/style.css
  docs/.nojekyll             防止 Pages 走 Jekyll
数据落盘：
  data/events-YYYY-MM-DD.json   永久留档，重跑可重建全站
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import taxonomy

CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _write_text(path: Path, text: str) -> bool:
    """内容没变就不落盘，且一律用 LF 写盘。返回是否真的写了。

    两个目的：
    1. Windows 上默认会把 \\n 写成 \\r\\n，和 Linux 产物不一致，git diff 会整站翻新；
    2. 重跑一遍没有新内容时，产物一个字节都不该变，git diff 应该是空的。
    """
    data = text.encode("utf-8")
    if path.exists():
        try:
            if path.read_bytes() == data:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return True


def _date_cn(d: datetime) -> str:
    return f"{d.month} 月 {d.day} 日"


def _weekday(d: datetime) -> str:
    return WEEKDAYS[d.weekday()]


def _cn_from_date(date: str) -> str:
    d = datetime.strptime(date, "%Y-%m-%d")
    return f"{d.month} 月 {d.day} 日"


def _hm(d) -> str:
    if isinstance(d, str):
        d = datetime.fromisoformat(d)
    return d.strftime("%H:%M")


def _iso(d) -> str:
    return d.isoformat() if isinstance(d, datetime) else str(d)


def _env(templates_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["hm"] = _hm
    env.filters["cn_date"] = _cn_from_date
    return env


def _serialize(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        row = dict(e)
        # score 里带"距今多少小时"的时间衰减，每跑一次都会漂一点点；
        # 页面上不展示，留着只会让无变化的构建也产生 diff。
        row.pop("score", None)
        row["published_at_iso"] = _iso(e["published_at"])
        row["published_at"] = row["published_at_iso"]
        row["links"] = [
            {**link, "published_at": _iso(link["published_at"])} for link in e.get("links", [])
        ]
        out.append(row)
    return out


def _load_history(data_dir: Path, today: str) -> dict[str, dict]:
    history: dict[str, dict] = {}
    for path in sorted(data_dir.glob("events-*.json")):
        date = path.stem.replace("events-", "")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if date == today:
            continue
        history[date] = payload
    return history


def run(cfg: dict, events: list[dict], report: list[dict], summary: dict, now: datetime, root: Path) -> dict:
    site = dict(cfg.get("site", {}))
    paths = cfg.get("paths", {})
    data_dir = root / paths.get("data", "data")
    docs_dir = root / paths.get("docs", "docs")
    static_dir = root / paths.get("static", "static")
    templates_dir = root / paths.get("templates", "templates")

    base_url = (site.get("base_url") or "").rstrip("/")
    if not base_url:
        base_url = "https://example.github.io/car-daily"
        print("  [warn] site.base_url 未配置，RSS 里的绝对链接会指向示例域名")

    date_str = now.strftime("%Y-%m-%d")
    date_cn = _date_cn(now)
    weekday = _weekday(now)

    data_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    events_s = _serialize(events)
    payload = {
        "date": date_str,
        "generated_at": now.isoformat(),
        "overview": summary.get("overview", ""),
        "events": events_s,
        # 留存抓取报告时去掉耗时：ms 每轮都会变，会把无变化的构建变成一次 diff
        "sources": [{k: v for k, v in r.items() if k != "ms"} for r in report],
        "stats": {
            "events": len(events_s),
            "multi_source": sum(1 for e in events_s if e.get("multi_source")),
            # 是否启用了 AI 摘要（含命中缓存的情况），不是"这一轮有没有新调接口"
            "llm": bool(summary.get("online")),
        },
    }
    # 数据留档：内容没变就不重写，保留最早那次生成的 generated_at，
    # 这样同一天重跑不会因为时间戳产生 diff。
    events_path = data_dir / f"events-{date_str}.json"
    if events_path.exists():
        try:
            old = json.loads(events_path.read_text(encoding="utf-8"))
            same = {k: v for k, v in old.items() if k != "generated_at"} == {
                k: v for k, v in payload.items() if k != "generated_at"
            }
            if same and old.get("generated_at"):
                payload["generated_at"] = old["generated_at"]
        except (OSError, ValueError):
            pass
    written = 0
    if _write_text(events_path, json.dumps(payload, ensure_ascii=False, indent=1)):
        written += 1

    history = _load_history(data_dir, date_str)
    days = sorted(set(history) | {date_str})
    by_day = {
        d: (events_s if d == date_str else history[d].get("events", [])) for d in days
    }
    cats = taxonomy.build(by_day, cfg)
    tag_slug = {c["label"]: c["slug"] for c in cats}

    env = _env(templates_dir)
    ctx_base = {
        "site": site,
        # 页脚显示的"更新于"：跟这一页的数据日期走，而不是构建时刻，
        # 否则每次构建所有页面都会差一行，git 历史全是噪音。
        "updated": date_str,
        "window_hours": cfg.get("window_hours", 48),
        "cats": cats,
        "tag_slug": tag_slug,
    }

    def render(template: str, out_path: Path, root_prefix: str, page: str = "", **extra) -> None:
        nonlocal written
        ctx = dict(ctx_base)
        ctx.update(extra)
        ctx.update(root=root_prefix, page=page)
        html = env.get_template(template).render(**ctx)
        if _write_text(out_path, html):
            written += 1

    pending = [r for r in report if r["status"] in ("error", "pending")]

    # 今日首页
    render(
        "index.html",
        docs_dir / "index.html",
        "",
        page="home",
        date_cn=date_cn,
        weekday=weekday,
        overview=summary.get("overview", ""),
        events=events_s,
        multi_source_count=payload["stats"]["multi_source"],
        pending_sources=pending,
        prev_day=days[days.index(date_str) - 1] if days.index(date_str) > 0 else None,
        prev_cn=_cn_from_date(days[days.index(date_str) - 1]) if days.index(date_str) > 0 else "",
    )

    # 每一天一个固定链接的页面
    for date in days:
        is_today = date == date_str
        items = events_s if is_today else history[date].get("events", [])
        day_overview = (
            summary.get("overview", "") if is_today else history[date].get("overview", "")
        )
        d = datetime.strptime(date, "%Y-%m-%d").replace(hour=7, tzinfo=CN_TZ)
        idx = days.index(date)
        render(
            "day.html",
            docs_dir / date / "index.html",
            "../",
            page="day",
            updated=date,
            date=date,
            date_cn=_date_cn(d),
            weekday=_weekday(d),
            overview=day_overview or f"{date} 的 {len(items)} 条行业事件。",
            events=items,
            prev_day=days[idx - 1] if idx > 0 else None,
            prev_cn=_cn_from_date(days[idx - 1]) if idx > 0 else "",
            next_day=days[idx + 1] if idx + 1 < len(days) else None,
            next_cn=_cn_from_date(days[idx + 1]) if idx + 1 < len(days) else "",
        )

    # 历史（原「归档」）：按月分组，每天附 3 条头条，便于扫读
    months: list[dict] = []
    total_events = 0
    for date in sorted(days, reverse=True):
        d = datetime.strptime(date, "%Y-%m-%d")
        today_items = by_day[date]
        count = len(today_items)
        total_events += count
        key = d.strftime("%Y-%m")
        if not months or months[-1]["key"] != key:
            months.append({"key": key, "label": f"{d.year} 年 {d.month} 月", "days": [], "count": 0})
        months[-1]["days"].append(
            {
                "date": date,
                "label": f"{d.day} 日",
                "weekday": _weekday(d),
                "count": count,
                "tops": [e["title"] for e in today_items[:3]],
            }
        )
        months[-1]["count"] += 1
    render(
        "archive.html",
        docs_dir / "archive" / "index.html",
        "../",
        page="history",
        months=months,
        total_days=len(days),
        total_events=total_events,
    )

    # 分类总览
    render(
        "categories.html",
        docs_dir / "category" / "index.html",
        "../",
        page="cats",
        total_categories=len(cats),
    )

    # 单个分类
    for cat in cats:
        render(
            "category.html",
            docs_dir / "category" / cat["slug"] / "index.html",
            "../../",
            page="cats",
            updated=cat.get("newest") or date_str,
            cat=cat,
        )

    # RSS：每天一条
    feed_days = []
    for date in sorted(days, reverse=True)[:30]:
        d = datetime.strptime(date, "%Y-%m-%d").replace(hour=7, tzinfo=CN_TZ)
        items = events_s if date == date_str else history[date].get("events", [])
        overview = summary.get("overview", "") if date == date_str else history[date].get("overview", "")
        lines = [overview]
        for e in items[:5]:
            lines.append(f"· {e['title']}（{e['source']}）")
        feed_days.append(
            {
                "title": f"{_date_cn(d)} · 汽车行业 {len(items)} 条事件",
                "link": f"{base_url}/{date}/",
                "pubdate": format_datetime(d),
                "description": "\n".join(x for x in lines if x),
            }
        )
    # lastBuildDate 固定为当日 07:10，而不是构建时刻，否则每次重跑 RSS 都会变
    feed_build = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=7, minute=10, tzinfo=CN_TZ)
    render("feed.xml", docs_dir / "feed.xml", "", days=feed_days, last_build=format_datetime(feed_build))

    # 静态资源 & Pages 开关
    target_static = docs_dir / "static"
    if target_static.exists():
        shutil.rmtree(target_static)
    shutil.copytree(static_dir, target_static)
    _write_text(docs_dir / ".nojekyll", "")

    # 删掉 data 里已经不存在的日期页 / 分类页，避免产物里留下幽灵链接
    live_days = set(days)
    for child in docs_dir.iterdir():
        if child.is_dir() and _DATE_DIR.match(child.name) and child.name not in live_days:
            shutil.rmtree(child)
    cat_dir = docs_dir / "category"
    if cat_dir.exists():
        live_slugs = {c["slug"] for c in cats}
        for child in cat_dir.iterdir():
            if child.is_dir() and child.name not in live_slugs:
                shutil.rmtree(child)

    return {
        "docs": str(docs_dir),
        "days": len(days),
        "pages": len(days) + 4 + len(cats),
        "events": len(events_s),
        "categories": len(cats),
        "written": written,
    }