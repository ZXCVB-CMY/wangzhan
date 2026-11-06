"""摘要层：调 LLM 写 80–120 字摘要 + 一句点评 + 标签。

设计上只有两个要求：
  1) 只要 LLM 挂了/没配 Key/超时，就静默降级成离线兜底摘要 —— 页面永远能出。
  2) 摘要只允许改写原文，不允许补充事实；prompt 里明令禁止编造数字。

结果按事件 id 缓存到 data/.llm-cache.json，重跑不会重复花钱。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

try:
    import httpx
except ImportError:  # 骨架阶段允许没装
    httpx = None  # type: ignore

from .dedupe import bigrams, dice

CACHE_NAME = ".llm-cache.json"
# prompt 改了就把版本号 +1：旧缓存的事实口径不再可信，宁可重花一次钱（一次约 1 分钱）
PROMPT_VERSION = 2

SYSTEM_PROMPT = (
    "你是中国汽车行业的资深编辑。给你若干条新闻（标题 + 原文摘要 + 来源），"
    "为每条写：\n"
    "1. summary：80–120 字中文摘要，只改写原文已有的事实，不得新增数字、人名、机构、时间；"
    "原文信息不足时宁短勿编（但不要只复述标题，能写多少写多少）。\n"
    "2. comment：一句 15–30 字的点评，讲影响或看点，不要复述标题。\n"
    "3. tags：1–3 个中文标签，只能从 政策/召回/销量/财报/新车/价格/技术/电池/智驾/新能源/出海/基建/商用车 里选。\n"
    "最后再给一句 overview：60–90 字，概括今天这批新闻的主线（谁在推动、矛盾点在哪），"
    "同样只许用给定材料里的事实。\n"
    "只输出 JSON，格式：{\"overview\":\"...\",\"items\":[{\"id\":\"...\",\"summary\":\"...\",\"comment\":\"...\",\"tags\":[\"...\"]}]}"
)

_COMMENT_BY_TAG = {
    "政策": [
        "政策口径一变，产品规划和积分账本都要跟着重算。",
        "规矩定在前面，车企的排产表通常比公告更早动。",
        "这类文件看落地节奏，比看措辞更重要。",
    ],
    "召回": [
        "看是否为批次性工艺问题，涉及面比数量更值得关注。",
        "召回是结果，供应商和产线的整改才是原因。",
        "数量之外，更该留意有没有延伸到同平台车型。",
    ],
    "销量": [
        "总量之外更该看结构：谁在涨、涨在哪一档。",
        "单月数字受促销和交付节奏扰动，最好连着看三个月。",
        "批发与上险数的差额，往往比排名更能说明问题。",
    ],
    "新车": [
        "定价落在主销区间，真正的变量是交付节奏。",
        "参数已经卷到头，接下来拼的是渠道和交付。",
        "新车密度这么高，考验的是谁能把钱花在刀刃上。",
    ],
    "价格": [
        "终端先松动，年底冲量的信号已经很明确了。",
        "优惠一旦下去就很难收回，品牌溢价要重新算。",
        "价格战打到这个阶段，比的是成本结构而不是勇气。",
    ],
    "技术": [
        "离量产还有距离，先盯装车时间表而不是参数。",
        "技术发布会的看点不在指标，在谁先把成本打下来。",
        "路线之争还没收敛，押注单一方案的都有风险。",
    ],
    "新能源": [
        "渗透率往上走的同时，结构的差异比总量更值得看。",
        "新能源这条线的竞争，已经从增量转向存量替换。",
        "增速还在，但分蛋糕的人比去年多得多。",
    ],
    "出海": [
        "海外市场的门槛从关税转向合规，节奏会更慢。",
        "出口数字好看，售后和渠道才是长期成本。",
        "不同区域的打法差别很大，一份总数字掩盖很多。",
    ],
    "智驾": [
        "功能上车不难，难的是责任边界和长尾场景。",
        "智驾的竞争正在从能不能用，转向敢不敢用。",
        "法规和保险没跟上之前，宣传口径会先收紧。",
    ],
    "电池": [
        "电池路线的胜负，最终由成本和产能决定。",
        "参数领先不等于量产领先，先看产线什么时候通。",
        "材料价格一波动，这个环节的利润就重新分配。",
    ],
    "财报": [
        "财报看毛利和现金流，规模增长反而排在后面。",
        "亏损收窄是不是靠省钱，翻一下费用结构就知道。",
        "数字之外，管理层对下个季度的表述才是信号。",
    ],
    "商用车": [
        "商用车的复苏通常慢半拍，但弹性更实在。",
        "这条线看的是运价和置换周期，不是乘用车的逻辑。",
        "政策补贴退坡之后，真实需求才会显出来。",
    ],
}
_DEFAULT_COMMENTS = [
    "信息量有限，等更多信源补齐后再判断。",
    "先记一笔，看后续有没有跟进报道。",
    "单条新闻不足以下结论，值得放进观察名单。",
]


def _pick(seq: list[str], key: str) -> str:
    """按事件 id 稳定取一条，避免同一天的卡片出现一模一样的点评。"""
    if not seq:
        return _DEFAULT_COMMENTS[0]
    return seq[sum(map(ord, key)) % len(seq)]


def _fallback_summary(event: dict, lo: int, hi: int) -> str:
    text = (event.get("summary_raw") or "").strip()
    if not text:
        src = event.get("source") or "原文站点"
        return f"这条来自{src}，站点未给出导语，AI 摘要暂缺；点标题看原文。"
    if len(text) <= hi:
        return text
    cut = text[:hi]
    for sep in ("。", "；", "，", "、"):
        pos = cut.rfind(sep)
        if pos >= lo * 0.6:
            return cut[: pos + 1]
    return cut.rstrip("，、；") + "…"


def _fallback_comment(event: dict) -> str:
    key = str(event.get("id") or event.get("title") or "")
    for tag in event.get("tags") or []:
        if tag in _COMMENT_BY_TAG:
            return _pick(_COMMENT_BY_TAG[tag], key + tag)
    return _pick(_DEFAULT_COMMENTS, key)


def _fallback_overview(events: list[dict], date_str: str) -> str:
    if not events:
        return "今天没有满足条件的新事件。"
    counts: dict[str, int] = {}
    for e in events:
        for t in e.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    tags = "、".join(f"{k} {v} 条" for k, v in top) or "行业动态"
    lead = events[0]["title"]
    return f"共收录 {len(events)} 条事件，集中在{tags}。最受关注的是：{lead}。"


class Summarizer:
    def __init__(self, cfg: dict, data_dir: Path):
        self.cfg = cfg.get("llm", {})
        self.paths = cfg
        self.data_dir = data_dir
        self.cache_path = data_dir / CACHE_NAME
        self.cache: dict[str, dict] = {}
        if self.cache_path.exists():
            try:
                loaded = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.pop("__version__", None) == PROMPT_VERSION:
                    self.cache = loaded
            except Exception:
                self.cache = {}
        self.last_usage: dict = {}
        self.api_key = os.environ.get(self.cfg.get("api_key_env", "LLM_API_KEY"), "").strip()

    @property
    def online(self) -> bool:
        return bool(
            not getattr(self, "force_offline", False)
            and self.cfg.get("enabled", True)
            and self.api_key
            and httpx
        )

    def _key(self, event: dict) -> str:
        """缓存键带上素材指纹：同一事件补到了正文导语，就该重新生成摘要。"""
        material = (event.get("title", "") + "|" + (event.get("summary_raw") or "")).encode()
        return f"{event['id']}:{hashlib.md5(material).hexdigest()[:8]}"

    def run(self, events: list[dict], date_str: str) -> dict:
        lo = int(self.cfg.get("summary_min", 80))
        hi = int(self.cfg.get("summary_max", 120))

        pending = [e for e in events if self._key(e) not in self.cache]
        used_llm, error = False, ""

        if pending and self.online:
            try:
                result, overview_llm = self._call_llm(pending, date_str)
                self.cache.update(result)
                if overview_llm:
                    self.cache.setdefault("__overview__", {})[date_str] = overview_llm
                used_llm = True
            except Exception as exc:  # 网络/解析/限流，一律降级
                error = f"{type(exc).__name__}: {exc}"

        for event in events:
            hit = self.cache.get(self._key(event))
            if hit and hit.get("summary"):
                event["summary"] = _clamp(hit["summary"], lo, hi)
                event["comment"] = (hit.get("comment") or "").strip() or _fallback_comment(event)
                if hit.get("tags"):
                    event["tags"] = hit["tags"]
                event["summary_kind"] = "ai"
            else:
                event["summary"] = _fallback_summary(event, lo, hi)
                event["comment"] = _fallback_comment(event)
                event["summary_kind"] = "fallback"
            event["summary_dup"] = _dup_of_title(event)

        overview_cache = self.cache.get("__overview__") or {}
        overview = overview_cache.get(date_str)
        if not overview:
            overview = _fallback_overview(events, date_str)

        self._save()
        return {
            "used_llm": used_llm,
            "online": self.online,
            "error": error,
            "cached": len(events) - len(pending),
            "overview": overview,
            "usage": self.last_usage,
        }

    # ------------------------------------------------------------------ llm
    def _call_llm(self, events: list[dict], date_str: str = "") -> tuple[dict[str, dict], str]:
        max_items = int(self.cfg.get("max_items", 20))
        payload_items = [
            {
                "id": e["id"],
                "title": e["title"],
                "source": e.get("source", ""),
                "text": (e.get("summary_raw") or "")[:600],
            }
            for e in events[:max_items]
        ]
        body = {
            "model": self.cfg.get("model", "deepseek-chat"),
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"items": payload_items}, ensure_ascii=False)},
            ],
        }
        base = str(self.cfg.get("base_url", "https://api.deepseek.com/v1")).rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=float(self.cfg.get("timeout", 60))) as client:
            resp = client.post(f"{base}/chat/completions", headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()
        content = payload["choices"][0]["message"]["content"]
        self.last_usage = payload.get("usage") or {}

        data = _loads_json(content)
        by_id = {e["id"]: e for e in events[:max_items]}
        out: dict[str, dict] = {}
        for row in data.get("items", []):
            event = by_id.get(row.get("id") or "")
            if not event:
                continue
            out[self._key(event)] = {
                "summary": (row.get("summary") or "").strip(),
                "comment": (row.get("comment") or "").strip(),
                "tags": [t for t in (row.get("tags") or []) if isinstance(t, str)][:3],
            }
        if not out:
            raise ValueError("LLM 返回里没有可用的 items")
        overview = (data.get("overview") or "").strip()
        return out, _clamp(overview, 40, 140) if overview else ""

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache["__version__"] = PROMPT_VERSION
        tmp = self.cache_path.with_suffix(".tmp")
        # 显式 LF：缓存也要进仓库，Windows 默认 CRLF 会让 diff 整文件翻转
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(self.cache, ensure_ascii=False, indent=1))
        tmp.replace(self.cache_path)


def _dup_of_title(event: dict) -> bool:
    """摘要基本是标题复述时，卡片上就不再单独显示——否则同一句话读者要看两遍。"""
    summary = (event.get("summary") or "").strip()
    title = (event.get("title") or "").strip()
    if not summary or not title:
        return True
    if len(summary) > len(title) * 1.5:
        return False
    return dice(bigrams(summary), bigrams(title)) >= 0.6


def _clamp(text: str, lo: int, hi: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > hi:
        cut = text[:hi]
        pos = max(cut.rfind("。"), cut.rfind("；"))
        if pos > lo:
            return cut[: pos + 1]
        # 没有句号就在逗号处收，实在没有才硬截断——比在词中间砍一刀好读
        pos = max(cut.rfind("，"), cut.rfind("、"), cut.rfind(","))
        if pos > lo * 0.75:
            return cut[:pos] + "…"
        return cut.rstrip("，、；,") + "…"
    return text


def _loads_json(content: str) -> dict:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S)
    start, end = content.find("{"), content.rfind("}")
    if start >= 0 and end > start:
        content = content[start : end + 1]
    return json.loads(content)