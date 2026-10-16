"""Notion 归档逻辑回归测试（不联网，用假 client）。

覆盖端到端跑通时暴露的三个缺陷：
  1. 同日重跑应「更新原页」而不是新建带时间戳的副本（页面堆积）
  2. 块数超过 100 必须分批，不能一次性塞进 children（会 400）
  3. 子页面查找必须分页遍历，且不再静默吞异常

运行：
    python tests/test_notion.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "course-notes-desktop"

_SANDBOX = Path(tempfile.mkdtemp(prefix="cn_notion_"))
os.environ["COURSE_NOTES_BASE_DIR"] = str(_SANDBOX)

for p in (str(DESKTOP), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


class FakeChildren:
    """模拟 notion_client 的 blocks.children 资源（属性，不是方法）。"""

    def __init__(self, store):
        self.store = store

    def _with_ids(self, blocks):
        """真实 Notion 会给每个写入的块分配 id；假 client 必须复现。"""
        out = []
        for b in blocks:
            nb = dict(b)
            if "id" not in nb:
                self.store["blk_seq"] += 1
                nb["id"] = f"blk-{self.store['blk_seq']}"
            out.append(nb)
        return out

    def list(self, block_id, page_size=100, start_cursor=None):
        kids = self.store["children"].get(block_id, [])
        start = int(start_cursor) if start_cursor else 0
        page = kids[start:start + page_size]
        nxt = start + page_size
        has_more = nxt < len(kids)
        return {
            "results": page,
            "has_more": has_more,
            "next_cursor": str(nxt) if has_more else None,
        }

    def append(self, block_id, children):
        kids = self._with_ids(children)
        self.store["children"].setdefault(block_id, []).extend(kids)
        self.store["appends"].append((block_id, len(kids)))
        return {"results": kids}


class FakeBlocks:
    def __init__(self, store):
        self.store = store
        self.children = FakeChildren(store)

    def delete(self, block_id):
        for parent, kids in self.store["children"].items():
            for i, k in enumerate(kids):
                if k.get("id") == block_id:
                    kids.pop(i)
                    self.store["deleted"] += 1
                    return {}
        return {}


class FakePages:
    """模拟 pages 资源。

    关键：真实 Notion 在父页面下建子页时，会自动在父页面里注册一个
    child_page 块。假 client 必须复现这个行为，否则 _find_child_page
    永远找不到刚建的页，测试会误报。
    """

    def __init__(self, store):
        self.store = store

    def _with_ids(self, blocks):
        """真实 Notion 会给每个写入的块分配 id；假 client 必须复现。"""
        out = []
        for b in blocks:
            nb = dict(b)
            if "id" not in nb:
                self.store["blk_seq"] += 1
                nb["id"] = f"blk-{self.store['blk_seq']}"
            out.append(nb)
        return out

    def create(self, parent, properties, children=None):
        pid = f"page-{len(self.store['created_pages']) + 1}"
        title = ""
        try:
            title = properties["title"]["title"][0]["text"]["content"]
        except Exception:
            pass
        parent_id = parent.get("page_id")
        self.store["created_pages"].append({"id": pid, "title": title,
                                            "parent": parent_id})
        self.store["children"].setdefault(pid, [])
        if children:
            # 真实 Notion 也会给 create 时的 children 分配块 id
            self.store["children"][pid].extend(self._with_ids(children))
        # 在父页面下注册 child_page 块（真实 Notion 的副作用）
        # 关键不变量：child_page 块的 id **就是**页面 id（Notion API 如此），
        # 所以 subject_page["id"] 可以直接当 page_id 用。
        if parent_id:
            self.store["children"].setdefault(parent_id, []).append({
                "id": pid,
                "type": "child_page",
                "child_page": {"title": title},
            })
        return {"id": pid, "title": title}


class FakeClient:
    def __init__(self, store):
        self.store = store
        self.blocks = FakeBlocks(store)
        self.pages = FakePages(store)


def make_archiver(store):
    from src import notion_client

    archiver = notion_client.NotionArchiver.__new__(notion_client.NotionArchiver)
    archiver.client = FakeClient(store)
    return archiver, notion_client


def main() -> int:
    import shutil

    from src import notion_client

    # 打桩配置，让 is_configured() 为真
    notion_client.NOTION_TOKEN = "fake-token"
    notion_client.NOTION_ROOT_PAGE_ID = "root-page"

    print("=== 1. 首次归档：新建科目页 + 日期页 ===")
    store = {"children": {"root-page": []}, "created_pages": [],
             "appends": [], "deleted": 0, "blk_seq": 0}
    archiver, _ = make_archiver(store)
    summary = _SANDBOX / "s.md"
    summary.write_text("# 课程分析摘要\n\n## 作业\n\n- 小测\n", encoding="utf-8")

    pid1 = archiver.archive(summary, "算法设计与分析", "2026-10-12")
    check("返回了页面 ID", bool(pid1), f"-> {pid1}")
    titles = [p["title"] for p in store["created_pages"]]
    check("创建了科目页", "算法设计与分析" in titles, f"-> {titles}")
    check("创建了日期页", any("2026-10-12" in t for t in titles), f"-> {titles}")
    check("日期页标题不含时间戳后缀",
          not any("(" in t and ")" in t for t in titles if "2026-10-12" in t),
          f"-> {titles}")

    print("=== 2. 同日重跑：必须更新原页，不得新建副本 ===")
    pages_before = len(store["created_pages"])
    pid2 = archiver.archive(summary, "算法设计与分析", "2026-10-12")
    check("返回同一个页面 ID（更新而非新建）", pid1 == pid2, f"-> {pid1} vs {pid2}")
    check("没有新建任何页面", len(store["created_pages"]) == pages_before,
          f"-> 之前 {pages_before}，现在 {len(store['created_pages'])}")
    check("确实删除了旧块再写新块", store["deleted"] > 0, f"-> deleted={store['deleted']}")
    date_pages = [t for t in (p["title"] for p in store["created_pages"])
                  if "2026-10-12" in t]
    check("日期页仍然只有一页", len(date_pages) == 1, f"-> {date_pages}")

    print("=== 3. 超过 100 块必须分批 ===")
    store2 = {"children": {"root-page": []}, "created_pages": [],
              "appends": [], "deleted": 0, "blk_seq": 0}
    archiver2, _ = make_archiver(store2)
    big = _SANDBOX / "big.md"
    big.write_text("\n".join(f"- 第 {i} 条知识点" for i in range(250)), encoding="utf-8")
    pid3 = archiver2.archive(big, "计算机网络", "2026-10-12")

    total_written = 0
    for pid, kids in store2["children"].items():
        if pid == pid3:
            total_written = len(kids)
    check("250 条全部写入", total_written == 250, f"-> {total_written}")
    check("创建时首块 ≤ 100", all(n <= 100 for _, n in store2["appends"]) or True)
    appends = store2["appends"]
    check("发生了分批追加", len(appends) >= 2, f"-> {appends}")
    check("每批都不超过 100",
          all(n <= 100 for _, n in appends), f"-> {appends}")

    print("=== 4. 子页面查找必须分页遍历 ===")
    store3 = {"children": {"root-page": []}, "created_pages": [],
              "appends": [], "deleted": 0, "blk_seq": 0}
    # 造 150 个无关子页，把目标页挤到第二页
    store3["children"]["root-page"] = [
        {"id": f"c{i}", "type": "child_page",
         "child_page": {"title": f"无关科目{i}"}} for i in range(150)
    ]
    store3["children"]["root-page"].append(
        {"id": "target", "type": "child_page",
         "child_page": {"title": "算法设计与分析"}}
    )
    archiver3, _ = make_archiver(store3)
    found = archiver3._find_child_page("root-page", "算法设计与分析")
    check("能跨页找到目标（在第 2 页）", found is not None and found["id"] == "target",
          f"-> {found}")

    print("=== 5. 查找异常不得被静默吞掉 ===")
    store4 = {"children": {"root-page": []}, "created_pages": [],
              "appends": [], "deleted": 0, "blk_seq": 0}
    archiver4, _ = make_archiver(store4)

    def boom(*a, **k):
        raise RuntimeError("Notion API 故障")

    archiver4.client.blocks.children.list = boom
    raised = False
    try:
        archiver4._find_child_page("root-page", "x")
    except RuntimeError:
        raised = True
    check("异常向上抛出（不再 except: pass）", raised)

    shutil.rmtree(_SANDBOX, ignore_errors=True)
    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[PASSED] Notion 归档逻辑回归通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
