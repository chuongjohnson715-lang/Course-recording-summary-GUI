"""课表候选优先级回归测试。

要保证两件事：
  1. 仓库自带的 课表.example.xls 能被找到（clone 后开箱可用）
  2. 用户放入自己的 课表.xls 后，真实课表优先于示例

不碰真实课表：在隔离目录里用空的 BASE_DIR 验证候选顺序。

运行：
    .venv\\Scripts\\python.exe tests\\test_schedule_priority.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SANDBOX = Path(tempfile.mkdtemp(prefix="cn_schedprio_"))
print(f"隔离目录: {_SANDBOX}")

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


def main() -> int:
    # --- 场景 A：只有示例课表（模拟 clone 后的状态）---
    print("\nA) 只有 课表.example.xls")
    os.environ["COURSE_NOTES_BASE_DIR"] = str(_SANDBOX)
    for m in [k for k in list(sys.modules) if k.startswith("config")]:
        del sys.modules[m]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    example = _SANDBOX / "课表.example.xls"
    shutil.copy(ROOT / "课表.example.xls", example)

    from config import paths  # noqa: E402

    found = paths.find_schedule_file()
    check("能找到示例课表", found is not None, f"实际 {found}")
    check("找到的确实是示例课表", found == example, f"实际 {found}")

    # --- 场景 B：放入真实课表，必须优先 ---
    print("\nB) 同时存在 课表.xls（用户真实）与 课表.example.xls")
    real = _SANDBOX / "课表.xls"
    shutil.copy(ROOT / "课表.example.xls", real)  # 内容无所谓，只看选中谁

    found2 = paths.find_schedule_file()
    check("优先选中真实课表", found2 == real, f"实际 {found2}")
    check("未回落到示例课表", found2 != example, f"实际 {found2}")

    # --- 场景 C：候选顺序里示例排在最后 ---
    print("\nC) 候选顺序")
    cands = [p.name for p in paths.SCHEDULE_CANDIDATES]
    check("示例课表在候选列表中", "课表.example.xls" in cands)
    idx_real = min(i for i, n in enumerate(cands) if n in ("课表.xls", "课表.xlsx"))
    idx_ex = cands.index("课表.example.xls")
    check("示例课表排在所有真实课表之后", idx_ex > idx_real,
          f"真实 idx={idx_real}, 示例 idx={idx_ex}")

    print("\nD) 解析示例课表")
    from core.schedule import load_schedule_xls  # noqa: E402

    weekly = load_schedule_xls(ROOT / "课表.example.xls")
    total = sum(len(v) for v in weekly.values())
    check("示例课表解析出 7 天", len(weekly) == 7, f"实际 {len(weekly)}")
    check("示例课表解析出课程", total > 0, f"实际 {total}")

    shutil.rmtree(_SANDBOX, ignore_errors=True)

    print()
    if failures:
        print(f"test_schedule_priority: {len(failures)} 项失败")
        return 1
    print("test_schedule_priority: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
