"""懂车帝 dongchedi.com 适配器（暂不接，可选补位）。

按计划先跳过：难度最高（搜索接口 + 反爬 + 登录墙），而它在方案里的角色只是"可选补位"，
缺了不影响每天出刊。等主源稳定后再评估。

如果以后要接，建议路径：
  1. /search?keyword=... 的 SSR 结果页里带 __NEXT_DATA__ / RENDER_DATA，优先解析它而不是爬 DOM。
  2. 只取"车系口碑/上市"类条目，避开需要登录的评论区。
  3. 失败一律跳过，不重试超过 2 次。
"""

from __future__ import annotations

from .base import RawItem, SourceNotReady

SOURCE = {
    "id": "dongchedi",
    "label": "懂车帝",
    "weight": 0.6,
}


def fetch(limit: int = 30) -> list[RawItem]:
    raise SourceNotReady("懂车帝按计划跳过（可选补位，不影响出刊）。")