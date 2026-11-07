"""筛选、打分、聚类。

1) 时间窗：只留最近 N 小时的（默认 48）。
2) 打分：基础分 + 事件类别权重 + 来源权重 + 时间新鲜度。
3) 聚类：同一事件的多源报道合并成一张卡片，保留最早来源 + 全部链接。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from .dedupe import similarity

# 类别 -> 命中关键词。顺序即优先级，用于并列时的稳定排序。
CATEGORY_RULES: dict[str, list[str]] = {
    "召回": ["召回", "缺陷", "备案"],
    "政策": ["政策", "征求意见", "工信部", "发改委", "四部门", "法规", "准入", "试点", "双积分", "购置税", "以旧换新", "补贴政策"],
    "销量": ["销量", "零售", "批发", "渗透率", "市占率", "上险量", "交付量", "交付"],
    "财报": ["财报", "营收", "净利润", "毛利率", "亏损", "业绩", "同比增", "同比降"],
    "新车": ["上市", "预售", "改款", "换代", "新车", "首发", "亮相"],
    "价格": ["降价", "优惠", "调价", "价格战", "万元起", "售价", "补贴"],
    "技术": ["平台", "电驱", "芯片", "激光雷达", "800v", "热效率", "架构", "甲醇", "氢燃料", "纪录", "风阻", "热管理"],
    "电池": ["电池", "电芯", "固态", "磷酸铁锂", "三元", "快充", "换电", "续航"],
    "智驾": ["智驾", "自动驾驶", "noa", "辅助驾驶", "端到端", "l3", "l2", "车路云"],
    "新能源": ["新能源", "纯电", "插混", "增程", "混动", "电动化", "电车"],
    "出海": ["出口", "出海", "海外", "关税", "欧洲市场", "东南亚", "全球化"],
    "基建": ["充电桩", "超充", "换电站", "电网", "补能"],
    "商用车": ["重卡", "轻卡", "客车", "物流车", "商用车", "牵引车", "轻客"],
}

# 品牌词表：判断"两条稿子说的是不是同一家"。中文全名 + 常见英文名。
BRANDS: set[str] = {
    "比亚迪", "特斯拉", "蔚来", "小鹏", "理想", "零跑", "哪吒", "极氪", "岚图", "阿维塔",
    "深蓝", "问界", "智界", "享界", "尊界", "小米", "华为", "吉利", "银河", "领克",
    "极星", "沃尔沃", "极狐", "北汽", "上汽", "荣威", "名爵", "智己", "飞凡", "五菱",
    "宝骏", "广汽", "埃安", "传祺", "一汽", "红旗", "奔腾", "东风", "长安", "启源",
    "长城", "哈弗", "魏牌", "坦克", "欧拉", "奇瑞", "星途", "捷途", "江淮", "海马",
    "众泰", "华晨", "宝马", "奔驰", "奥迪", "大众", "保时捷", "宾利", "丰田", "雷克萨斯",
    "本田", "日产", "英菲尼迪", "三菱", "马自达", "斯巴鲁", "铃木", "现代", "起亚",
    "福特", "林肯", "雪佛兰", "别克", "凯迪拉克", "道奇", "标致", "雪铁龙", "雷诺",
    "法拉利", "玛莎拉蒂", "劳斯莱斯", "迈凯伦", "路特斯", "捷豹", "路虎", "通用",
    "极越", "高合", "威马", "天际", "爱驰", "合众", "大运", "远程", "陕汽", "重汽",
    "解放", "福田", "宇通", "金龙", "中通", "安凯", "极石", "远航", "江铃", "九龙",
    "honda", "jeep", "ds", "nio", "xpeng", "leapmotor", "zeekr", "byd", "tesla",
}

# 事件词：同一品牌下用来区分"销量/召回/财报"这类完全不同的事件。
EVENT_WORDS: set[str] = {
    "召回", "销量", "交付", "上市", "预售", "发布", "财报", "营收", "亏损", "降价",
    "优惠", "补贴", "政策", "出口", "进博会", "车展", "碰撞", "起火", "自燃", "事故",
    "破产", "裁员", "合作", "投资", "融资", "建厂", "投产", "固态电池", "快充", "换电",
    "智驾", "自动驾驶", "芯片", "激光雷达", "召回计划", "财报电话会", "季度", "月销",
}

_TAG_TITLE_WEIGHT = 3
_TAG_SUMMARY_WEIGHT = 1
_TAG_MIN_SCORE = 3
_TAG_MAX = 3


def infer_tags(item: dict) -> list[str]:
    """按命中次数加权：标题权重高，摘要只做补充；取前 1–3 个。"""
    title = item.get("title", "").lower()
    summary = (item.get("summary_raw") or "").lower()
    scored: list[tuple[int, int, str]] = []
    for order, (cat, words) in enumerate(CATEGORY_RULES.items()):
        score = sum(_TAG_TITLE_WEIGHT for w in words if w in title)
        score += sum(_TAG_SUMMARY_WEIGHT for w in words if w in summary)
        if score:
            scored.append((score, order, cat))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [cat for score, _, cat in scored if score >= _TAG_MIN_SCORE][:_TAG_MAX]


def _anchors(item: dict) -> tuple[set[str], set[str]]:
    text = (item.get("title", "") + " " + (item.get("summary_raw") or "")).lower()
    return {b for b in BRANDS if b in text}, {w for w in EVENT_WORDS if w in text}


def score_item(item: dict, now: datetime, cfg: dict) -> float:
    weights = cfg.get("rank", {}).get("category_weights", {})
    halflife = float(cfg.get("rank", {}).get("recency_halflife_hours", 18))
    scale = float(cfg.get("rank", {}).get("source_weight_scale", 0.6))

    cat = max((float(weights.get(t, 0)) for t in item["tags"]), default=0.0)
    src = float(cfg.get("sources", {}).get(item["source_id"], {}).get("weight", 0.5)) * scale
    hours = max(0.0, (now - item["published_at"]).total_seconds() / 3600)
    fresh = 0.5 ** (hours / halflife)

    return round(1.0 + cat + src + 1.5 * fresh, 4)


def within_window(items: list[dict], now: datetime, hours: int) -> list[dict]:
    cutoff = now - timedelta(hours=hours)
    return [i for i in items if i["published_at"] >= cutoff]


def cluster(items: list[dict], threshold: float = 0.45) -> list[dict]:
    """按分数倒序贪心聚类；簇的标题/链接取最早那条。

    threshold 只是"品牌相同、文本也比较像"的门槛，另外两条通道更严：
    文本几乎一致（同稿转载）直接合；品牌 + 事件词都撞上才合。
    模板化标题（"X 携 Y 亮相进博会"）在二元组上能到 0.4–0.55，光靠文本阈值必然误合并，
    所以必须先过品牌词表。
    """
    ordered = sorted(items, key=lambda i: (-i["score"], i["published_at"]))
    anchors = {id(i): _anchors(i) for i in ordered}
    groups: list[list[dict]] = []

    def merge_ok(item: dict, head: dict) -> bool:
        sim = similarity(item, head)
        if sim >= 0.72:  # 同稿转载 / 轻微改写，不需要看品牌
            return True
        (bi, ei), (bh, eh) = anchors[id(item)], anchors[id(head)]
        if not (bi & bh):  # 品牌对不上，宁可分开也别合错
            return False
        if ei & eh and sim >= 0.26:
            return True
        return sim >= threshold

    for item in ordered:
        placed = False
        for group in groups:
            if merge_ok(item, group[0]):
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    events = [_to_event(g) for g in groups]
    events.sort(key=lambda e: (-e["score"], e["published_at"]))
    return events


def _to_event(group: list[dict]) -> dict:
    group = sorted(group, key=lambda i: i["published_at"])
    head = group[0]
    links, seen_sources, seen_urls = [], set(), set()
    for item in group:
        if item["url"] in seen_urls:
            continue
        seen_urls.add(item["url"])
        links.append(
            {
                "source": item["source_label"],
                "url": item["url"],
                "title": item["title"],
                "published_at": item["published_at"],
            }
        )
        seen_sources.add(item["source_label"])

    tags: list[str] = []
    for item in group:
        for t in item.get("tags") or []:
            if t not in tags:
                tags.append(t)

    summary_raw = max((i.get("summary_raw", "") for i in group), key=len, default="")
    cover = next((i["cover"] for i in group if i.get("cover")), "")
    stamps = [i["fetched_at"] for i in group if i.get("fetched_at")]

    return {
        "id": hashlib.sha1(head["url"].encode()).hexdigest()[:10],
        "title": head["title"],
        "url": head["url"],
        "source": head["source_label"],
        "sources": sorted(seen_sources),
        "published_at": head["published_at"],
        # 一个事件可能被多个源报道，收录时间取最早的那次：第一次被我们看到的时间
        "fetched_at": min(stamps) if stamps else None,
        "summary_raw": summary_raw,
        "cover": cover,
        "tags": tags,
        "score": max(i["score"] for i in group),
        "links": links,
        "multi_source": len(seen_sources) > 1,
    }


def run(items: list[dict], now: datetime, cfg: dict) -> tuple[list[dict], dict]:
    hours = int(cfg.get("window_hours", 48))
    limit = int(cfg.get("daily_limit", 15))
    threshold = float(cfg.get("dedupe", {}).get("cluster_threshold", 0.45))

    for item in items:
        item["tags"] = infer_tags(item)
        item["score"] = score_item(item, now, cfg)

    in_window = within_window(items, now, hours)
    events = cluster(in_window, threshold)
    stats = {
        "in_window": len(in_window),
        "out_of_window": len(items) - len(in_window),
        "events": len(events),
        "multi_source": sum(1 for e in events if e["multi_source"]),
    }
    return events[:limit], stats