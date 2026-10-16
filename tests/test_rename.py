"""改名逻辑回归测试（由 sensevoice/test_rename_dryrun.py 升级而来）。

用途：验证 core/schedule.py 合并两份实现后，行为与重构前的 golden 基线完全一致。
只做预测，永远不真正改名（dry_run=True 且快照校验 mtime/大小）。

运行：
    python tests/test_rename.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import paths                                    # noqa: E402
from core.schedule import (                                 # noqa: E402
    WEEKDAY_NAMES,
    load_schedule,
    rename_by_schedule,
)

GOLDEN = Path(__file__).resolve().parent / "golden_rename.json"

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}: got={got!r} want={want!r}")
        failures.append(label)


def snapshot() -> dict:
    """记录 sounds/ 里每个文件的大小与 mtime，确保测试没动文件。"""
    snap = {}
    for p in sorted(paths.SOUNDS_DIR.glob("*")):
        if p.is_file():
            st = p.stat()
            snap[p.name] = (st.st_size, int(st.st_mtime))
    return snap


def main() -> int:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    before = snapshot()

    # 本测试依赖「你自己的真实录音 + 真实课表」，属于本机专用回归基线。
    # 公开仓库里既没有 sounds/ 也没有真实课表，因此这里优雅跳过而不是报错。
    if not golden:
        print("未找到 golden 基线（tests/golden_rename.json），跳过。")
        print("该基线依赖本机真实录音与课表，属于本地专用；")
        print("如需生成：放入你的课表与录音后运行 tests/make_golden.py")
        return 0

    schedule_path = paths.find_schedule_file()
    print(f"课表文件: {schedule_path}")
    check("找到课表文件", schedule_path is not None, True)
    if schedule_path is None:
        print("没有课表，无法回归。")
        return 1

    weekly = load_schedule(schedule_path, verbose=True)
    total_slots = sum(len(v) for v in weekly.values())
    expected_slots = golden.get("total_slots")
    if expected_slots is not None:
        check("课表门次总数", total_slots, expected_slots)

    print("\n=== 一周课表概览 ===")
    for wd, slots in sorted(weekly.items()):
        names = sorted({c for c, _, _, _ in slots})
        print(f"  {WEEKDAY_NAMES[wd]}: {', '.join(names) if names else '（无课）'}")

    print("\n=== 各录音改名预测（dry-run）===")
    golden_map = golden.get("files", {})
    for f in sorted(paths.SOUNDS_DIR.glob("*.m4a")):
        final_path, course, date_str, matched = rename_by_schedule(
            f.resolve(), weekly, dry_run=True, verbose=True
        )
        want = golden_map.get(f.name)
        if want is None:
            print(f"  [SKIP] {f.name} 不在 golden 里（新增文件，未固定预期）")
            continue
        check(f"{f.name} -> 预测名", final_path.name, want["predicted_name"])
        check(f"{f.name} -> 课程名", course, want["course"])
        check(f"{f.name} -> 日期", date_str, want["date"])

    # 关键不变量：dry-run 绝不能改动任何文件
    print("\n=== 不变量检查：文件未被改动 ===")
    check("sounds/ 文件快照未变化", snapshot(), before)

    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项不符合 golden 基线：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[PASSED] 改名逻辑与 golden 基线一致，且未改动任何文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
