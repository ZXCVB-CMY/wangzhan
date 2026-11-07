"""首次收录时间（first-seen）。

"收录"指这条链接第一次被我们抓到的时刻，不是本轮构建的时刻。必须持久化：
每轮重算会把它推成"现在"，既失真，也会让无变化的构建产生 diff。

状态存在 `data/.first-seen.json`（url -> ISO 时间），只增不减，
超过 `KEEP_DAYS` 天的条目清掉，避免文件无限长大。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sources.base import iso

from .clean import parse_time

KEEP_DAYS = 21
STATE_FILE = ".first-seen.json"


def _state_path(data_dir: Path) -> Path:
    return data_dir / STATE_FILE


def _read_state(data_dir: Path) -> dict[str, str]:
    path = _state_path(data_dir)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError):
            pass

    # 第一次运行：拿历史 events 文件的 generated_at 近似"首次见到"，
    # 免得今天已经抓到的那批显示成本次重建的时间。
    seeded: dict[str, str] = {}
    for f in sorted(data_dir.glob("events-*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stamp = str(payload.get("generated_at") or "")
        if not stamp:
            continue
        for event in payload.get("events") or []:
            urls = [event.get("url")] + [link.get("url") for link in event.get("links") or []]
            for url in urls:
                if url and url not in seeded:
                    seeded[url] = stamp
    return seeded


def _write_state(path: Path, state: dict[str, str]) -> None:
    text = json.dumps(dict(sorted(state.items())), ensure_ascii=False, indent=0) + "\n"
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def stamp(items: list[dict], data_dir: Path, now: datetime, keep_days: int = KEEP_DAYS) -> int:
    """给每条 item 打上 `fetched_at`（首次收录时间），返回本轮新增的条数。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    state = _read_state(data_dir)
    now_iso = iso(now)
    added = 0

    for item in items:
        url = item.get("url") or ""
        if not url:
            continue
        first = state.get(url)
        if first is None:
            state[url] = now_iso
            first = now_iso
            added += 1
        item["fetched_at"] = parse_time(first) or now

    cutoff = now - timedelta(days=keep_days)
    for url in [u for u, t in state.items() if (parse_time(t) or now) < cutoff]:
        del state[url]

    _write_state(_state_path(data_dir), state)
    return added