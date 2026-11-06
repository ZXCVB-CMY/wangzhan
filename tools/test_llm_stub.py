"""用本地假接口验证 LLM 通路：请求格式、JSON 解析、缓存、渲染。"""
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import yaml

from pipeline import clean, dedupe, fetch, rank, render, summarize
from sources.base import now_cn

CALLS = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        CALLS.append((self.headers.get("Authorization"), body))
        items = json.loads(body["messages"][1]["content"])["items"]
        out = {
            "overview": "今日主线在政策与价格两端：积分办法修订压缩正积分供给，车企一边调价一边抢年底的量。",
            "items": [
                {
                    "id": it["id"],
                    "summary": f"（LLM）关于「{it['title'][:12]}」的改写摘要，只复述原文事实，长度控制在区间内，不新增任何数字与机构名称。",
                    "comment": "这条的看点在于节奏，不在数字本身。",
                    "tags": ["政策", "销量", "技术"],
                }
                for it in items
            ],
        }
        payload = json.dumps(
            {"choices": [{"message": {"content": "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"}}]},
            ensure_ascii=False,
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
cfg["llm"]["base_url"] = f"http://127.0.0.1:{port}/v1"
cfg["sources"]["mock"]["enabled"] = True
os.environ["LLM_API_KEY"] = "test-key"

now = now_cn()
raw, report = fetch.run(cfg, verbose=False)
items = clean.clean_all(raw, now)
kept, dropped = dedupe.dedupe(items, cfg["dedupe"]["near_dup_threshold"])
events, stats = rank.run(kept, now, cfg)

tmp = Path(tempfile.mkdtemp())
summarizer = summarize.Summarizer(cfg, tmp)
result = summarizer.run(events, now.strftime("%Y-%m-%d"))

print("online:", summarizer.online, "| used_llm:", result["used_llm"], "| error:", result["error"] or "-")
print("http calls:", len(CALLS), "| auth:", CALLS[0][0] if CALLS else "-")
print("model:", CALLS[0][1]["model"] if CALLS else "-")
print("items sent:", len(json.loads(CALLS[0][1]["messages"][1]["content"])["items"]) if CALLS else 0)
print("summaries from LLM:", sum(1 for e in events if e.get("summary_kind") == "ai"), "/", len(events))
print("overview:", result["overview"])
print("sample summary:", events[0]["summary"][:60])
print("cache written:", (tmp / ".llm-cache.json").exists(), "| keys:", len(json.loads((tmp / '.llm-cache.json').read_text(encoding='utf-8'))))

before = len(CALLS)
summarizer2 = summarize.Summarizer(cfg, tmp)
result2 = summarizer2.run(events, now.strftime("%Y-%m-%d"))
print("cached run -> used_llm:", result2["used_llm"], "| cached:", result2["cached"], "| new calls:", len(CALLS) - before)

# 渲染到临时目录，绝不碰仓库里的 data/ 与 docs/
site = tmp / "site"
shutil.copytree(ROOT / "templates", site / "templates")
shutil.copytree(ROOT / "static", site / "static")
render.run(cfg, events, report, result, now, site)
html = (site / "docs/index.html").read_text(encoding="utf-8")
print("AI 摘要 badge on page:", html.count("AI 摘要"))
print("rendered into:", site)
srv.shutdown()