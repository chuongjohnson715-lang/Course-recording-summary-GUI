"""查看「算法设计与分析」科目页下已有哪些日期页，避免重复归档。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOK = json.loads((ROOT / ".notion_oauth.json").read_text(encoding="utf-8"))
URL = TOK["mcp_url"]
ACCESS = TOK["access_token"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

SUBJECT = "3f37c7a8-e30b-81c3-b5c4-ff502a57376d"   # 算法设计与分析
ROOT_PAGE = "3f37c7a8-e30b-811a-85ed-ede76de03dbb"  # 课堂笔记

_sid = None
_seq = [0]


def rpc(method, params=None, notify=False):
    global _sid
    _seq[0] += 1
    payload = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    if not notify:
        payload["id"] = _seq[0]
    headers = {
        "Authorization": f"Bearer {ACCESS}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": UA,
        "MCP-Protocol-Version": "2025-06-18",
    }
    if _sid:
        headers["Mcp-Session-Id"] = _sid
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            s = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
            if s:
                _sid = s
            body = r.read().decode("utf-8", errors="replace")
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] {e.read().decode('utf-8','replace')[:400]}")
        return None
    if notify:
        return None
    if "event-stream" in ctype or "\ndata:" in body:
        for line in body.splitlines():
            if line.strip().startswith("data:"):
                try:
                    return json.loads(line.strip()[5:].strip())
                except json.JSONDecodeError:
                    continue
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def call_tool(name, args):
    res = rpc("tools/call", {"name": name, "arguments": args})
    if not res:
        return None
    content = ((res.get("result") or {}).get("content")) or []
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


def main() -> int:
    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "course-notes", "version": "1.0"}})
    rpc("notifications/initialized", {}, notify=True)

    print("=== 算法设计与分析 科目页内容 ===")
    txt = call_tool("notion-fetch", {"id": SUBJECT})
    if txt:
        print(txt[:2500])
    print()

    print("=== 课堂笔记 根页面内容（看科目页列表） ===")
    txt2 = call_tool("notion-fetch", {"id": ROOT_PAGE})
    if txt2:
        print(txt2[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
