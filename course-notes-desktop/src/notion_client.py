"""Notion 归档（按科目长期累积）。

修复了三个真实缺陷（都在真机端到端跑时暴露出来）：
  1. 同日重跑会新建「带时间戳的副本」而不是更新原页 -> 页面无限堆积。
     现在：找到同日页就**替换其内容**（先删旧块再写新块），页面保持唯一。
  2. 整篇 Markdown 一次性塞进 children -> 超过 Notion 的 100 块上限会 400。
     现在：分块写入，每批不超过 MAX_BLOCKS_PER_REQUEST。
  3. _find_child_page 只列第一页、且 `except: pass` 吞掉所有异常
     -> 科目页多了会找不到（然后重复建页），出错也毫无提示。
     现在：分页遍历到底，异常记录并重新抛出（调用方可判断）。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .config import NOTION_ROOT_PAGE_ID, NOTION_TOKEN

try:
    from notion_client import Client
except ImportError:
    Client = None

# Notion API 硬限制：单次请求 children 最多 100 个块
MAX_BLOCKS_PER_REQUEST = 100
# 单个 rich_text 内容上限 2000 字符，超出要切分
MAX_RICH_TEXT = 2000


def _chunk(seq: list, size: int) -> list[list]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


class NotionArchiver:
    """将课程分析结果写入 Notion，按科目页 -> 日期页结构归档。"""

    def __init__(self) -> None:
        if Client is None:
            raise RuntimeError(
                "缺少 notion-client 包。请运行：pip install -r requirements.txt"
            )
        self.client = Client(auth=NOTION_TOKEN) if NOTION_TOKEN else None

    def is_configured(self) -> bool:
        return bool(Client and NOTION_TOKEN and NOTION_ROOT_PAGE_ID)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _norm_course(self, course_name: str | None) -> str:
        if not course_name:
            return "未识别科目"
        # 去掉课次编号等，例如 "大学物理（B）（2-2）" -> "大学物理"
        name = course_name.strip()
        name = re.sub(r"[（(][^）)]*[）)]", "", name)
        return name.strip() or "未识别科目"

    def _list_child_pages(self, parent_id: str) -> list[dict]:
        """分页列出父页面下的所有 child_page。

        旧实现只取第一页（默认最多 100 条）且吞掉异常，
        科目一多就会漏找、进而重复建页。
        """
        if not self.client:
            return []
        pages: list[dict] = []
        cursor = None
        while True:
            kwargs = {"block_id": parent_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self.client.blocks.children.list(**kwargs)
            for child in resp.get("results", []):
                if child.get("type") == "child_page":
                    pages.append(child)
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
            if not cursor:
                break
        return pages

    def _find_child_page(self, parent_id: str, title: str) -> dict | None:
        """在父页面下查找指定标题的子页面（分页遍历）。

        异常不再静默吞掉：向上抛出，避免「找不到 -> 重复建页」这种
        静默的数据污染。
        """
        if not self.client:
            return None
        for child in self._list_child_pages(parent_id):
            if child.get("child_page", {}).get("title") == title:
                return child
        return None

    def _rich_text(self, content: str) -> list[dict]:
        """把长文本切成符合 Notion 上限的 rich_text 数组。"""
        if not content:
            return [{"type": "text", "text": {"content": ""}}]
        return [
            {"type": "text", "text": {"content": content[i:i + MAX_RICH_TEXT]}}
            for i in range(0, len(content), MAX_RICH_TEXT)
        ]

    def _markdown_to_blocks(self, text: str) -> list[dict]:
        """极简 Markdown 分块：按行识别标题与列表。"""
        blocks: list[dict] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            # 跳过 YAML front matter 的分隔线，避免在 Notion 里出现孤立的 ---
            if line == "---":
                continue
            if line.startswith("### "):
                blocks.append({
                    "object": "block", "type": "heading_3",
                    "heading_3": {"rich_text": self._rich_text(line[4:].strip())},
                })
            elif line.startswith("## "):
                blocks.append({
                    "object": "block", "type": "heading_2",
                    "heading_2": {"rich_text": self._rich_text(line[3:].strip())},
                })
            elif line.startswith("# "):
                blocks.append({
                    "object": "block", "type": "heading_1",
                    "heading_1": {"rich_text": self._rich_text(line[2:].strip())},
                })
            elif line.startswith("- "):
                blocks.append({
                    "object": "block", "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": self._rich_text(line[2:].strip())},
                })
            elif line.startswith("> "):
                blocks.append({
                    "object": "block", "type": "quote",
                    "quote": {"rich_text": self._rich_text(line[2:].strip())},
                })
            else:
                blocks.append({
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": self._rich_text(line)},
                })
        return blocks

    def _append_blocks(self, page_id: str, blocks: list[dict]) -> None:
        """分批追加块，规避单请求 100 块上限。"""
        if not self.client or not blocks:
            return
        for batch in _chunk(blocks, MAX_BLOCKS_PER_REQUEST):
            self.client.blocks.children.append(block_id=page_id, children=batch)

    def _clear_page(self, page_id: str) -> int:
        """删除页面的所有子块，返回删除数量。"""
        if not self.client:
            return 0
        deleted = 0
        cursor = None
        while True:
            kwargs = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self.client.blocks.children.list(**kwargs)
            results = resp.get("results", [])
            for blk in results:
                block_id = blk.get("id")
                if not block_id:
                    continue
                try:
                    self.client.blocks.delete(block_id=block_id)
                    deleted += 1
                except Exception as exc:  # noqa: BLE001
                    # 单个块删不掉（例如子页面需先移出）不应中断整体流程
                    print(f"  [Notion] 删除块 {block_id} 失败: {exc}")
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
            if not cursor:
                break
        return deleted

    def _create_page(self, parent_id: str, title: str, blocks: list[dict]) -> dict:
        """在父页面下创建子页面，块分批写入。"""
        if not self.client:
            raise RuntimeError("Notion 未配置")

        first, rest = blocks[:MAX_BLOCKS_PER_REQUEST], blocks[MAX_BLOCKS_PER_REQUEST:]
        page = self.client.pages.create(
            parent={"page_id": parent_id},
            properties={"title": {"title": [{"text": {"content": title}}]}},
            children=first,
        )
        self._append_blocks(page["id"], rest)
        return page

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def archive(
        self,
        summary_path: Path,
        course_name: str | None,
        record_date: str | None,
    ) -> str:
        """归档摘要到 Notion。

        同一科目 + 同一日期**只有一页**：已存在则替换其内容，不再新建副本。
        返回该页面的 ID。
        """
        if not self.is_configured():
            raise RuntimeError(
                "Notion 未配置：请在 .env 中设置 NOTION_TOKEN 和 NOTION_ROOT_PAGE_ID"
            )

        course = self._norm_course(course_name)
        date_title = f"{record_date or '未知日期'} · {course}"
        summary_text = summary_path.read_text(encoding="utf-8")
        blocks = self._markdown_to_blocks(summary_text)

        # 1) 定位或创建科目页
        subject_page = self._find_child_page(NOTION_ROOT_PAGE_ID, course)
        if subject_page:
            subject_id = subject_page["id"]
        else:
            subject = self.client.pages.create(
                parent={"page_id": NOTION_ROOT_PAGE_ID},
                properties={"title": {"title": [{"text": {"content": course}}]}},
            )
            subject_id = subject["id"]

        # 2) 同日页已存在 -> 替换内容（修复「新建带时间戳副本」的堆积问题）
        existing = self._find_child_page(subject_id, date_title)
        if existing:
            page_id = existing["id"]
            removed = self._clear_page(page_id)
            self._append_blocks(page_id, blocks)
            print(f"  [Notion] 已更新同日页面（清除 {removed} 个旧块，写入 {len(blocks)} 个新块）")
            return page_id

        # 3) 不存在 -> 新建
        page = self._create_page(subject_id, date_title, blocks)
        print(f"  [Notion] 已新建日期页面（{len(blocks)} 个块）")
        return page["id"]

    def _now_short(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%H%M")
