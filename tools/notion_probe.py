"""用拿到的 OAuth token 验证 Notion MCP 连通性，并列出可见页面。

MCP 走 JSON-RPC over Streamable HTTP：
  1. initialize
  2. notifications/initialized
  3. tools/list  （看有哪些工具）
  4. tools/call notion-search 找「课堂笔记」根页面
"""
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

_session_id: str | None = None


def rpc(method: str, params: dict | None = None, *, notify: bool = False) -> dict | None:
    """发一个 JSON-RPC 请求；解析 SSE 或 JSON 响应。"""
    global _session_id
    payload = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    if not notify:
        payload["id"] = 1

    headers = {
        "Authorization": f"Bearer {ACCESS}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": UA,
        "MCP-Protocol-Version": "2025-06-18",
    }
    if _session_id:
        headers["Mcp-Session-Id"] = _session_id

    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
            if sid:
                _session_id = sid
            body = r.read().decode("utf-8", errors="replace")
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:600]
        print(f"  [HTTP {e.code}] {detail}")
        return None

    if notify:
        return None

    # SSE 格式：逐行找 data:
    if "text/event-stream" in ctype or body.lstrip().startswith("event:") or "\ndata:" in body:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        print(f"  [无法解析] {body[:300]}")
        return None


def main() -> int:
    print("=== 1. initialize ===")
    res = rpc("initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "course-notes", "version": "1.0"},
    })
    if not res:
        print("  [FAIL] 初始化失败")
        return 1
    info = (res.get("result") or {}).get("serverInfo") or {}
    print(f"  [OK] 服务器: {info.get('name')} {info.get('version')}")
    print(f"  session id: {_session_id}")

    rpc("notifications/initialized", {}, notify=True)

    print("\n=== 2. tools/list ===")
    res = rpc("tools/list", {})
    tools = ((res or {}).get("result") or {}).get("tools") or []
    print(f"  [OK] 可用工具 {len(tools)} 个")
    for t in tools[:30]:
        print(f"     - {t['name']}")

    print("\n=== 3. 搜「课堂笔记」根页面 ===")
    for q in ("课堂笔记", "课堂"):
        res = rpc("tools/call", {
            "name": "notion-search",
            "arguments": {"query": q, "page_size": 10},
        })
        if not res:
            continue
        content = ((res.get("result") or {}).get("content")) or []
        text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        print(f"  --- 查询 {q!r} 命中 {len(text)} 字符 ---")
        print(text[:1500])
        if text.strip():
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
