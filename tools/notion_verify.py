"""验证刚归档的页面确实存在、内容正确、且没有重复页。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from notion_archive import ROOT_PAGE_ID, NotionMCP  # noqa: E402

SUBJECT = "3f37c7a8-e30b-81c3-b5c4-ff502a57376d"


def main() -> int:
    n = NotionMCP()

    print("=== 1. 科目页下的日期页清单 ===")
    txt = n._fetch_text(SUBJECT)
    pages = re.findall(
        r'<page url="https://app\.notion\.com/p/([0-9a-f]{32})"[^>]*>([^<]*)</page>', txt)
    for pid, title in pages:
        print(f"  - {title}")
    dates = [t for _, t in pages if "2026-10-12" in t]
    print(f"\n  2026-10-12 的页面数: {len(dates)}  {'[OK] 无重复' if len(dates) == 1 else '[FAIL] 有重复！'}")

    print("\n=== 2. 新页面内容 ===")
    target = None
    for pid, title in pages:
        if "2026-10-12" in title:
            target = f"{pid[:8]}-{pid[8:12]}-{pid[12:16]}-{pid[16:20]}-{pid[20:]}"
            break
    if not target:
        print("  [FAIL] 找不到新页面")
        return 1
    body = n._fetch_text(target)
    print(body[:2200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
