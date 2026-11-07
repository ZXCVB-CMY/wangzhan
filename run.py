#!/usr/bin/env python3
"""汽车行业日报 · 构建入口。

一次运行：抓取 → 清洗 → 去重 → 排序/聚类 → 摘要 → 渲染 → docs/

用法：
  python run.py                     # 用 config.yaml 里启用的源
  python run.py --sources mock      # 只跑指定源（逗号分隔）
  python run.py --date 2026-11-04   # 补跑某一天（只影响时间窗与文件名）
  python run.py --no-llm            # 跳过 LLM，用规则兜底摘要
  python run.py --check             # 只做抓取与统计，不渲染
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from pipeline import clean, dedupe, fetch, rank, render, seen, summarize
from sources.base import CN_TZ

ROOT = Path(__file__).resolve().parent


def load_config() -> dict:
    path = ROOT / "config.yaml"
    if not path.exists():
        sys.exit(f"找不到配置文件：{path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="汽车行业日报构建")
    parser.add_argument("--sources", default="", help="逗号分隔的源 id，默认用配置启用项")
    parser.add_argument("--date", default="", help="YYYY-MM-DD，默认今天（北京时间）")
    parser.add_argument("--no-llm", action="store_true", help="不用 LLM，走规则兜底")
    parser.add_argument("--check", action="store_true", help="只抓取统计，不渲染")
    args = parser.parse_args()

    cfg = load_config()
    started = time.time()

    if args.date:
        now = datetime.strptime(args.date, "%Y-%m-%d").replace(hour=7, minute=30, tzinfo=CN_TZ)
    else:
        now = datetime.now(CN_TZ)

    print(f"== 汽车日报构建 == {now:%Y-%m-%d %H:%M} (UTC+8)")
    print(f"   时间窗：最近 {cfg.get('window_hours', 48)} 小时｜上限 {cfg.get('daily_limit', 15)} 条")

    # 1. 抓取
    only = [s.strip() for s in args.sources.split(",") if s.strip()] or None
    raw, report = fetch.run(cfg, verbose=False, only=only)
    ok = [r for r in report if r["status"] == "ok"]
    print(f"\n[1/6] 抓取：{len(raw)} 条原始数据，{len(ok)}/{len(report)} 个源有产出")
    for r in report:
        flag = {"ok": "OK", "empty": "--", "pending": "待接入", "error": "失败"}[r["status"]]
        detail = f"{r['count']} 条 {r['ms']}ms" if r["status"] in ("ok", "empty") else (r.get("error") or "")
        print(f"      [{flag:>4}] {r['label']:<12} {detail}")

    if args.check:
        print(f"\n（--check 模式，未渲染）耗时 {time.time() - started:.1f}s")
        return 0

    # 2-3. 清洗 + 去重
    cleaned = clean.clean_all(raw, now)
    kept, dropped = dedupe.dedupe(cleaned, cfg.get("dedupe", {}).get("near_dup_threshold", 0.9))
    data_dir = ROOT / cfg.get("paths", {}).get("data", "data")
    new_seen = seen.stamp(kept, data_dir, now)
    print(
        f"\n[2/6] 清洗：{len(cleaned)} 条有效；[3/6] 去重：丢弃 {dropped} 条重复；"
        f"首次收录 +{new_seen}"
    )

    # 4. 排序与聚类
    events, stats = rank.run(kept, now, cfg)
    print(
        f"[4/6] 排序：窗内 {stats['in_window']} 条，窗外 {stats['out_of_window']} 条，"
        f"聚成 {stats['events']} 个事件（多源报道 {stats['multi_source']} 个）"
    )

    # 5. 摘要
    summarizer = summarize.Summarizer(cfg, ROOT / cfg.get("paths", {}).get("data", "data"))
    if args.no_llm:
        summarizer.force_offline = True
    summary = summarizer.run(events, now.strftime("%Y-%m-%d"))
    mode = "LLM" if summary["used_llm"] else ("缓存" if summary["cached"] else "规则兜底")
    note = f"（{summary['error']}）" if summary.get("error") else ""
    usage = summary.get("usage") or {}
    if usage.get("total_tokens"):
        note += f"（{usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)} tokens）"
    print(f"[5/6] 摘要：{mode}模式{note}")

    # 6. 渲染
    result = render.run(cfg, events, report, summary, now, ROOT)
    print(
        f"[6/6] 渲染：{result['events']} 条事件 → {result['docs']}"
        f"（{result['pages']} 个页面，{result['days']} 天，{result['categories']} 个分类）"
    )
    total_files = result["pages"] + 1  # 页面 + feed.xml
    if result.get("written", total_files) == 0:
        print("      产物无变化：0 个文件重写")
    else:
        print(f"      实际写入 {result['written']} 个文件，其余未变")
    print(f"\n总耗时 {time.time() - started:.1f}s。本地预览：file:///{result['docs'].replace(chr(92), '/')}/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())