"""中国汽车工业信息网 autoinfo.org.cn 适配器（待接）。

今日实测（2026-11-05）：
  · 首页只有 447 字节，是 Vue + Vite 的 SPA，正文靠 JS 渲染。
  · 但接口是裸露的，前端 bundle 里能看到一批 JSON 路径，例如
      /api/search/suggest
      /api/newData/searchData/draggingPageInit
      /api/newData/displayData/salesData
      /api/dict/sysDictData/selectDictDataByType
  · 资讯频道在 /workInformation/... 路由下，需要找到对应的 list 接口。

TODO（明天）：
  1. 打开 /workInformation/enterpriseInfo/news，抓 XHR，找出列表接口与分页参数。
  2. 确认是否要登录/签名；若需要，退回 Playwright 渲染取 DOM。
  3. 落成 fetch(limit)，映射到 RawItem（标题/时间/导语/链接）。
"""

from __future__ import annotations

from .base import RawItem, SourceNotReady

SOURCE = {
    "id": "autoinfo",
    "label": "中国汽车工业信息网",
    "weight": 0.8,
}

# 明天验证用的候选接口，先记在这里
CANDIDATE_APIS = [
    "/api/search/suggest",
    "/api/newData/searchData/draggingPageInit",
    "/api/newData/searchData/draggingQuery",
]


def fetch(limit: int = 30) -> list[RawItem]:
    raise SourceNotReady(
        "autoinfo 是 SPA，需要先定位资讯列表接口；见 sources/autoinfo.py 顶部说明。"
    )