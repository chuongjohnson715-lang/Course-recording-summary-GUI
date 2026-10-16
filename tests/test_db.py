"""db 层回归测试。

覆盖三个真实踩过的坑（都是「桌面程序从未成功跑过一次」的成因）：
  1. get_or_create_task 递归自死锁（外层写事务未提交又开新连接）
  2. row_to_dict 对 sqlite3.Row 调 .get() -> AttributeError
  3. 失败重试成功后，旧的 error 文本没被清空

在隔离沙箱里运行，不碰真实 tasks.db。

运行：
    python tests/test_db.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "course-notes-desktop"

# 必须在导入 src.* 之前把沙箱根目录定好
_SANDBOX = Path(tempfile.mkdtemp(prefix="cn_dbtest_"))
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


def main() -> int:
    import shutil

    from src import db

    db.init_db()
    audio = _SANDBOX / "sounds" / "x.m4a"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")

    print("=== 1. 建任务 / 读已存在任务（曾抛 AttributeError）===")
    try:
        t = db.get_or_create_task(audio)
        check("首次 get_or_create_task 成功", t["id"] >= 1, f"-> {t}")
    except Exception as exc:  # noqa: BLE001
        check("首次 get_or_create_task 成功", False, f"-> {type(exc).__name__}: {exc}")
        shutil.rmtree(_SANDBOX, ignore_errors=True)
        return 1

    try:
        t2 = db.get_or_create_task(audio)
        check("二次 get_or_create_task 正常（不再 database is locked）", t2["id"] == t["id"])
        check("meta 字段解析为 dict", isinstance(t2["meta"], dict), f"-> {t2['meta']!r}")
    except Exception as exc:  # noqa: BLE001
        check("二次 get_or_create_task 正常", False, f"-> {type(exc).__name__}: {exc}")

    print("=== 2. 失败 -> 重试成功，错误必须被清空 ===")
    db.update_task(t["id"], status="failed", step="处理失败", error="网络抖动")
    got = db.get_task_by_id(t["id"])
    check("失败时写入 error", got["error"] == "网络抖动", f"-> {got['error']!r}")

    db.update_task(t["id"], status="done", step="完成", error=None)
    got = db.get_task_by_id(t["id"])
    check("成功后 error 被清空", got["error"] is None, f"-> {got['error']!r}")
    check("status 变为 done", got["status"] == "done", f"-> {got['status']!r}")
    check("done 时写入 finished_at", bool(got["finished_at"]), f"-> {got['finished_at']!r}")

    print("=== 3. 不传 error 时不得改动已有值 ===")
    db.update_task(t["id"], error="诊断信息")
    db.update_task(t["id"], step="只改步骤")
    got = db.get_task_by_id(t["id"])
    check("未传 error 时保留原值", got["error"] == "诊断信息", f"-> {got['error']!r}")
    check("step 已更新", got["step"] == "只改步骤", f"-> {got['step']!r}")

    print("=== 4. 未完成任务查询 ===")
    pending = db.get_pending_or_unfinished()
    check("done 任务不出现在未完成列表", all(x["id"] != t["id"] for x in pending),
          f"-> {[x['id'] for x in pending]}")

    shutil.rmtree(_SANDBOX, ignore_errors=True)
    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[PASSED] db 层回归通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
