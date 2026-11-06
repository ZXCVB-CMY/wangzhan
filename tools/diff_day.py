"""比较两天的 data/events-*.json，回答"哪条新闻变了"。

HTML 不适合当变更记录：一次构建会牵动十几个页面，行尾、排序、分类增删
都会制造噪音。真正该对比的是数据层——一天一个 JSON、结构稳定、不重写。

用法：
    python tools/diff_day.py                # 最近两天
    python tools/diff_day.py 2026-11-06 2026-11-07
    python tools/diff_day.py --all 2026-11-01 2026-11-07   # 区间汇总

判定：先按 url 对齐（同一条新闻重发会保持 url），url 对不上的再用标题相似度
（复用 pipeline.dedupe.similarity）找"改了标题的同一件事"。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.dedupe import similarity  # noqa: E402

REWRITE_THRESHOLD = 0.55


def load(date: str) -> dict:
    path = ROOT / "data" / f"events-{date}.json"
    if not path.exists():
        raise SystemExit(f"没有这一天的数据：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def days() -> list[str]:
    return sorted(p.stem.replace("events-", "") for p in (ROOT / "data").glob("events-*.json"))


def label(e: dict) -> str:
    return f"「{e.get('title', '')}」（{e.get('source', '')}）"


def compare(old: dict, new: dict) -> dict:
    o_events = old.get("events", [])
    n_events = new.get("events", [])

    # 1) 按 url 对齐
    o_by_url = {e.get("url", ""): e for e in o_events if e.get("url")}
    n_by_url = {e.get("url", ""): e for e in n_events if e.get("url")}
    removed_left = [e for e in o_events if e.get("url") not in n_by_url]
    added_left = [e for e in n_events if e.get("url") not in o_by_url]

    same, changed = [], []
    for url, o in o_by_url.items():
        n = n_by_url.get(url)
        if not n:
            continue
        d = {
            "url": url,
            "title_before": o.get("title", ""),
            "title_after": n.get("title", ""),
            "summary_before": o.get("summary", ""),
            "summary_after": n.get("summary", ""),
            "source": n.get("source", ""),
        }
        (changed if (d["title_before"] != d["title_after"] or d["summary_before"] != d["summary_after"]) else same).append(d)

    # 2) 剩下的按标题相似度认成"同一件事、换了标题"
    rewrites = []
    for n in list(added_left):
        best, best_score = None, 0.0
        for o in removed_left:
            score = similarity(o, n)
            if score > best_score:
                best, best_score = o, score
        if best is not None and best_score >= REWRITE_THRESHOLD:
            rewrites.append({"before": best, "after": n, "score": best_score})
            added_left.remove(n)
            removed_left.remove(best)

    added = [e for e in added_left if e not in [r["after"] for r in rewrites]]
    removed = [e for e in removed_left if e not in [r["before"] for r in rewrites]]

    return {
        "old_count": len(o_events),
        "new_count": len(n_events),
        "same": same,
        "changed": changed,
        "added": added,
        "removed": removed,
        "rewrites": rewrites,
    }


def show(d_from: str, d_to: str, result: dict) -> None:
    print(f"\n{d_from} → {d_to}：{result['old_count']} 条 → {result['new_count']} 条")
    print(
        f"  未变 {len(result['same'])} / 有更新 {len(result['changed'])} / "
        f"新增 {len(result['added'])} / 消失 {len(result['removed'])} / 改写 {len(result['rewrites'])}"
    )
    if result["added"]:
        print("\n  [新增]")
        for e in result["added"]:
            print(f"    + {label(e)}")
    if result["removed"]:
        print("\n  [消失]")
        for e in result["removed"]:
            print(f"    - {label(e)}")
    if result["rewrites"]:
        print("\n  [标题改写，判定为同一件事]")
        for r in result["rewrites"]:
            print(f"    ~ {r['before'].get('title','')}\n      → {r['after'].get('title','')}  (相似度 {r['score']:.2f})")
    if result["changed"]:
        print("\n  [内容有更新]")
        for c in result["changed"]:
            if c["title_before"] != c["title_after"]:
                print(f"    * 标题：{c['title_before']}\n           → {c['title_after']}")
            else:
                print(f"    * 摘要：{c['title_after']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="比较两天的数据，看哪条新闻变了")
    ap.add_argument("old", nargs="?", help="较早的日期 YYYY-MM-DD，缺省=数据里的倒数第二天")
    ap.add_argument("new", nargs="?", help="较晚的日期 YYYY-MM-DD，缺省=数据里的最后一天")
    args = ap.parse_args()

    all_days = days()
    if not args.old or not args.new:
        if len(all_days) < 2:
            raise SystemExit(f"只有 {len(all_days)} 天数据，没法比较（先攒两天，或用参数指定）")
        d_from, d_to = (args.old, args.new) if args.old and args.new else (all_days[-2], all_days[-1])
    else:
        d_from, d_to = args.old, args.new

    result = compare(load(d_from), load(d_to))
    show(d_from, d_to, result)


if __name__ == "__main__":
    main()