"""分类体系：把自由标签映射成稳定的 URL slug，并汇总每个分类下的事件。

标签来自两处：`rank.CATEGORY_RULES` 自动推断的 6 类，以及各数据源自带的标签。
两者都是中文自由文本，直接做路径会在 URL 里出现百分号编码，也不好手敲，
所以统一映射成 ASCII slug：

- `config.yaml` 的 `categories` 里声明过的标签用指定 slug（如 政策 → policy）
- 没声明过的用 `t-<sha1 前 6 位>`，保证链接稳定、随时可加新分类

`build()` 把全部历史天的数据摊平成「分类 → 事件列表」，供渲染层出页面。
"""

from __future__ import annotations

import hashlib

# 没在 config 里声明时的兜底顺序（按重要性排）
DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("policy", "政策"),
    ("recall", "召回"),
    ("sales", "销量"),
    ("newcar", "新车"),
    ("price", "价格"),
    ("tech", "技术"),
    ("nev", "新能源"),
    ("export", "出海"),
    ("adas", "智驾"),
    ("battery", "电池"),
    ("infra", "基建"),
    ("earnings", "财报"),
    ("commercial", "商用车"),
]

# 单个分类页最多列多少条，避免几年后一页几千条
MAX_EVENTS = 80


def table(cfg: dict) -> list[tuple[str, str]]:
    """从配置读 [(slug, label)]，缺省或格式不对时回退到内置表。"""
    raw = cfg.get("categories")
    out: list[tuple[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("slug") and item.get("label"):
                out.append((str(item["slug"]), str(item["label"])))
            elif isinstance(item, str) and item:
                out.append((_auto_slug(item), item))
    return out or list(DEFAULT_CATEGORIES)


def _auto_slug(tag: str) -> str:
    return "t-" + hashlib.sha1(tag.encode("utf-8")).hexdigest()[:6]


def mapping(cfg: dict) -> dict[str, str]:
    """标签 → slug。声明过的优先，其余按需生成。"""
    return {label: slug for slug, label in table(cfg)}


def slug_for(tag: str, cfg: dict) -> str:
    return mapping(cfg).get(tag) or _auto_slug(tag)


def build(days_events: dict[str, list[dict]], cfg: dict) -> list[dict]:
    """{date: events} → 分类列表，按「配置顺序 → 事件数」排序。

    每个分类：slug / label / count / day_count / newest / oldest / events / truncated
    events 里的每条都带 `day`（YYYY-MM-DD），渲染时用来显示日期。
    """
    declared = table(cfg)
    order = {label: i for i, (_, label) in enumerate(declared)}
    slugs = {label: slug for slug, label in declared}

    buckets: dict[str, list[dict]] = {}
    for date, events in days_events.items():
        for event in events:
            for tag in event.get("tags") or []:
                buckets.setdefault(tag, []).append({**event, "day": date})

    cats: list[dict] = []
    for tag, items in buckets.items():
        items.sort(key=lambda e: e.get("published_at") or "", reverse=True)
        dates = sorted({e["day"] for e in items})
        cats.append(
            {
                "slug": slugs.get(tag) or _auto_slug(tag),
                "label": tag,
                "count": len(items),
                "day_count": len(dates),
                "newest": dates[-1],
                "oldest": dates[0],
                "events": items[:MAX_EVENTS],
                "truncated": len(items) > MAX_EVENTS,
            }
        )

    cats.sort(key=lambda c: (order.get(c["label"], len(declared)), -c["count"], c["label"]))
    return cats