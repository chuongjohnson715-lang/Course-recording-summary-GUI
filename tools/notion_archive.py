"""用 Notion MCP（OAuth token）归档课程摘要。

与桌面程序的 notion_client.py 目标一致：
  课堂笔记(根) -> 科目页 -> 日期页
但走的是 Notion 官方 MCP，因此不需要手建 integration。

用法：
    python tools/notion_archive.py --summary <path> --course <名> --date <YYYY-MM-DD> [--topic <主题>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOK_FILE = ROOT / ".notion_oauth.json"

ROOT_PAGE_ID = "3f37c7a8-e30b-811a-85ed-ede76de03dbb"   # 课堂笔记
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_sid = None
_seq = [0]


def _rpc(url, access, method, params=None, notify=False):
    global _sid
    _seq[0] += 1
    payload = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    if not notify:
        payload["id"] = _seq[0]
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": UA,
        "MCP-Protocol-Version": "2025-06-18",
    }
    if _sid:
        headers["Mcp-Session-Id"] = _sid
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            s = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
            if s:
                _sid = s
            body = r.read().decode("utf-8", errors="replace")
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:400]}") from None
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


class NotionMCP:
    def __init__(self) -> None:
        tok = json.loads(TOK_FILE.read_text(encoding="utf-8"))
        self.url = tok["mcp_url"]
        self.access = tok["access_token"]
        _rpc(self.url, self.access, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "course-notes", "version": "1.0"}})
        _rpc(self.url, self.access, "notifications/initialized", {}, notify=True)

    def call(self, name: str, args: dict) -> str:
        res = _rpc(self.url, self.access, "tools/call",
                   {"name": name, "arguments": args})
        if not res:
            return ""
        if "error" in res:
            raise RuntimeError(f"{name} 出错: {res['error']}")
        content = ((res.get("result") or {}).get("content")) or []
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")

    # ------------------------------------------------------------------
    def _fetch_text(self, page_id: str) -> str:
        """取页面的 XML 描述。

        notion-fetch 返回的 content[].text 往往是一个 JSON 串，真正的 XML
        在它的 "text" 字段里（引号被转义成 \\"）。必须解开这一层，
        否则正则匹配不到 <page url=...>。
        """
        raw = self.call("notion-fetch", {"id": page_id})
        if not raw:
            return ""
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and isinstance(obj.get("text"), str):
                return obj["text"]
        except json.JSONDecodeError:
            pass
        # 退化处理：把转义引号还原
        return raw.replace('\\"', '"')

    def find_child(self, parent_id: str, title: str) -> str | None:
        """在 parent 下找标题匹配的子页面，返回带连字符的 id。"""
        txt = self._fetch_text(parent_id)
        for m in re.finditer(
            r'<page url="https://app\.notion\.com/p/([0-9a-f]{32})"[^>]*>([^<]*)</page>',
            txt,
        ):
            pid, ptitle = m.group(1), m.group(2).strip()
            if ptitle == title:
                return f"{pid[:8]}-{pid[8:12]}-{pid[12:16]}-{pid[16:20]}-{pid[20:]}"
        return None

    def norm_course(self, name: str) -> str:
        n = re.sub(r"[（(][^）)]*[）)]", "", name or "").strip()
        return n or "未识别科目"


def to_markdown_blocks(text: str) -> str:
    """把摘要 md 转成 Notion 可接受的 markdown（保持原样即可，MCP 支持 md）。"""
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    ap.add_argument("--course", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--topic", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    summary_path = Path(args.summary)
    if not summary_path.exists():
        print(f"[FAIL] 找不到摘要: {summary_path}")
        return 1
    body = summary_path.read_text(encoding="utf-8")

    n = NotionMCP()
    course = n.norm_course(args.course)
    print(f"科目: {course}")

    # 1) 找科目页
    subject_id = n.find_child(ROOT_PAGE_ID, course)
    if subject_id:
        print(f"  [OK] 已有科目页: {subject_id}")
    else:
        print(f"  [..] 科目页不存在，将新建: {course}")
        if not args.dry_run:
            n.call("notion-create-pages", {
                "parent": {"type": "page_id", "page_id": ROOT_PAGE_ID},
                "pages": [{"properties": {"title": course}, "content": ""}],
            })
            subject_id = n.find_child(ROOT_PAGE_ID, course)
            print(f"  [OK] 已新建科目页: {subject_id}")

    if not subject_id:
        print("[FAIL] 拿不到科目页 id")
        return 1

    # 2) 日期页标题：沿用已有风格「YYYY-MM-DD 周X · 主题」
    import datetime
    d = datetime.date.fromisoformat(args.date)
    weekday_cn = "周" + "一二三四五六日"[d.weekday()]
    title = f"{args.date} {weekday_cn}"
    if args.topic:
        title += f" · {args.topic}"
    print(f"日期页标题: {title}")

    existing = n.find_child(subject_id, title)
    if existing:
        print(f"  [..] 同日页已存在: {existing} -> 更新内容")
        if not args.dry_run:
            n.call("notion-update-page", {
                "page_id": existing,
                "command": "replace_content",
                "new_str": body,
            })
            print("  [OK] 已更新")
        return 0

    print("  [..] 将新建日期页")
    if args.dry_run:
        print("  （dry-run，未写入）")
        return 0
    n.call("notion-create-pages", {
        "parent": {"type": "page_id", "page_id": subject_id},
        "pages": [{"properties": {"title": title}, "content": body}],
    })
    print("  [OK] 已新建并写入内容")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
