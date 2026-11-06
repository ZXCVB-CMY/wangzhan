"""调度层：按 config.yaml 跑所有启用的适配器。

一条硬规则：**任何单一源失败都不能让当天流程中断。**
失败就记进 report，页面照常生成，页面上标注"本日该源无数据"。
"""

from __future__ import annotations

import time
import traceback

from sources import load
from sources.base import SourceNotReady


def run(cfg: dict, verbose: bool = True, only: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """only 非空时只跑这些源（即使配置里是 enabled: false），方便调试。"""
    items: list[dict] = []
    report: list[dict] = []

    for source_id, conf in (cfg.get("sources") or {}).items():
        if only is not None:
            if source_id not in only:
                continue
        elif not conf.get("enabled"):
            continue
        label = conf.get("label", source_id)
        started = time.time()
        try:
            module = load(source_id)
            raw = module.fetch(limit=30) or []
            got = [i.to_dict() if hasattr(i, "to_dict") else dict(i) for i in raw]
            items.extend(got)
            report.append(
                {
                    "source_id": source_id,
                    "label": label,
                    "status": "ok" if got else "empty",
                    "count": len(got),
                    "ms": int((time.time() - started) * 1000),
                    "error": "",
                }
            )
            if verbose:
                print(f"  [ok]   {label:<12} {len(got):>3} 条  {int((time.time()-started)*1000)}ms")
        except SourceNotReady as exc:
            report.append(
                {
                    "source_id": source_id,
                    "label": label,
                    "status": "pending",
                    "count": 0,
                    "ms": int((time.time() - started) * 1000),
                    "error": str(exc),
                }
            )
            if verbose:
                print(f"  [skip] {label:<12} 未接入：{exc}")
        except Exception as exc:
            report.append(
                {
                    "source_id": source_id,
                    "label": label,
                    "status": "error",
                    "count": 0,
                    "ms": int((time.time() - started) * 1000),
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(limit=2),
                }
            )
            if verbose:
                print(f"  [fail] {label:<12} {type(exc).__name__}: {exc}")

    return items, report