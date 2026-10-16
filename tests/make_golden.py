"""用当前实现生成/刷新 golden 基线。

注意：golden 只在**确认实现行为正确**后刷新。正常流程是
先跑 tests/test_rename.py，人工核对 --dump 的结果，再刷新。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import paths                       # noqa: E402
from core.schedule import load_schedule, rename_by_schedule   # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden_rename.json"


def main() -> int:
    schedule_path = paths.find_schedule_file()
    if schedule_path is None:
        print("没有课表文件，无法生成 golden")
        return 1

    weekly = load_schedule(schedule_path, verbose=True)
    files = {}
    for f in sorted(paths.SOUNDS_DIR.glob("*.m4a")):
        final_path, course, date_str, matched = rename_by_schedule(
            f.resolve(), weekly, dry_run=True, verbose=False
        )
        files[f.name] = {
            "predicted_name": final_path.name,
            "course": course,
            "date": date_str,
            "matched": matched,
        }

    golden = {
        "_comment": (
            "golden 基线：由 tests/make_golden.py 从已验证的实现生成。"
            "改名逻辑改动后必须重新跑 tests/test_rename.py 并全部通过。"
        ),
        "_source": "sensevoice/test_rename_dryrun.py（重构前的实测基线，已比对一致）",
        "semester_start": "2026-08-31",
        "total_slots": sum(len(v) for v in weekly.values()),
        "files": files,
    }
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 {GOLDEN}（{len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
