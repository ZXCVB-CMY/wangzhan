"""中国汽车报 cnautonews.com 适配器（待接）。

今日实测（2026-11-05）：
  · 整站在 SafeLine / 雷池 WAF 后面，首页、列表页、robots.txt、甚至随便一个不存在的路径，
    返回的都是同一个 14591 字节的 JS 挑战页（DOM 里带 slg-bg / slg-title），httpx 一条都拿不到。
  · 所以纯 requests 方案在这里不成立，明天二选一：
      A. Playwright 无头 Chromium 过挑战（页面加载 5–8 秒后 cookie 落地），再取列表页 HTML。
      B. 换源（盖世汽车 / 汽车之家 / 乘联会等），把中国汽车报降为"能拿到就加"的附加源。

TODO（明天）：
  1. 用 Playwright 打开来源首页，等挑战通过后保存 storage_state 复用。
  2. 确认频道路径（文档写的 /yaowen/list_160_1.html 等目前被 WAF 挡住，无法验证真伪）。
  3. 解析列表 → 进入详情页取标题、时间、导语、封面。
  4. 只取最新 30 条；单站间隔 ≥ 1 秒；带真实 User-Agent 与联系邮箱。
"""

from __future__ import annotations

from .base import RawItem, SourceNotReady

SOURCE = {
    "id": "cnautonews",
    "label": "中国汽车报",
    "weight": 1.0,
}

CHANNELS = {
    "要闻": "/yaowen/list_{page}_{page}.html",
    "新能源": "/xinnengyuan/list_{page}_{page}.html",
    "智能网联": "/zhinengwl/list_{page}_{page}.html",
    "乘用车": "/chengyongcar/list_{page}_{page}.html",
    "商用车": "/shangyongcar/list_{page}_{page}.html",
}


def fetch(limit: int = 30) -> list[RawItem]:
    raise SourceNotReady(
        "中国汽车报需要浏览器过 WAF 挑战，尚未接入；见 sources/cnautonews.py 顶部说明。"
    )