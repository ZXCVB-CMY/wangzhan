"""抓取层公共约定。

每个适配器就是一个模块，暴露 ``SOURCE`` 元信息和 ``fetch(limit) -> list[RawItem]``。
适配器只负责"把网页变成结构化条目"，不做清洗、去重、排序、摘要——
那些统统交给 pipeline，明天换真源时不需要动后面任何一行代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any

CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


class SourceNotReady(NotImplementedError):
    """适配器还没接真源时抛这个，pipeline 会把它当成"本日该源无数据"跳过。"""


@dataclass
class RawItem:
    """一条抓取结果。字段尽量贴近最终 JSON，方便调试时肉眼比对。"""

    title: str
    url: str
    source_id: str
    source_label: str
    published_at: str = ""          # ISO8601，允许空，clean 阶段兜底
    summary_raw: str = ""           # 原文摘要/导语，可能带 HTML
    cover: str = ""                 # 封面图，允许空
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_cn() -> datetime:
    """北京时间当前时刻（不依赖系统时区设置）。"""
    return datetime.now(CN_TZ)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()