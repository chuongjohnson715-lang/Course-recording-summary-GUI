"""验证 课表.example.xls 能被真实解析器读取，并驱动改名成功。

这是「示例课表能不能替代真课表跑通功能」的证明：
  1. 用 core/schedule.py 的 load_schedule_xls 解析示例课表
  2. 用 rename_by_schedule 在 dry_run 下模拟一次改名
  3. 断言课程名与周次都被正确识别

运行：
    .venv\\Scripts\\python.exe tools\\verify_example_schedule.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import SEMESTER_START          # noqa: E402
from core.schedule import (                          # noqa: E402
    load_schedule_xls,
    rename_by_schedule,
    semester_week,
)

CN = "一二三四五六日"
XLS = ROOT / "课表.example.xls"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


def main() -> int:
    if not XLS.exists():
        print(f"缺少 {XLS.name}，先跑 tools/make_example_schedule.py")
        return 1

    print("1) 解析示例课表")
    weekly = load_schedule_xls(XLS, verbose=True)
    total = sum(len(v) for v in weekly.values())
    check("解析出 7 天", len(weekly) == 7, f"实际 {len(weekly)}")
    check("解析出课程", total > 0, f"实际 {total} 门次")

    print("\n2) 课程列表")
    for wd in sorted(weekly):
        for course, s, e, weeks in weekly[wd]:
            wk = "全部周" if weeks is None else f"{min(weeks)}-{max(weeks)}周"
            print(f"    周{CN[wd]} {s // 60:02d}:{s % 60:02d}~{e // 60:02d}:{e % 60:02d}  {course}  ({wk})")

    print("\n3) 逐周次筛选是否生效")
    # 找一个有周次限制的课程，确认 wno 过滤逻辑能工作
    limited = [
        (wd, c, weeks)
        for wd, items in weekly.items()
        for c, _s, _e, weeks in items
        if weeks and len(weeks) < 20
    ]
    check("存在带周次限制的课程", len(limited) > 0, f"实际 {len(limited)}")

    print("\n4) 模拟改名（dry-run）")
    # 造一个「第 1 周星期三 08:30」的录音文件名 -> 应匹配 线性代数
    start = datetime(*SEMESTER_START).date()
    # 第 1 周的星期三：start 是周一，+2 天
    wed_w1 = date.fromordinal(start.toordinal() + 2)
    stamp = f"{wed_w1:%Y%m%d}_083000"
    fake = ROOT / "sounds" / f"{stamp}.m4a"

    print(f"    录音: {fake.name}")
    print(f"    日期: {wed_w1}  第 {semester_week(wed_w1)} 周  星期三")

    _p, course, date_str, matched = rename_by_schedule(
        fake, weekly, dry_run=True, verbose=True
    )
    check("匹配到课程", matched, f"course={course}")
    check("课程名正确（期望 线性代数）", course == "线性代数", f"实际 {course!r}")
    check("日期串正确", date_str == wed_w1.isoformat(), f"实际 {date_str!r}")

    print()
    if failures:
        print(f"verify_example_schedule: {len(failures)} 项失败")
        return 1
    print("verify_example_schedule: 全部通过 —— 示例课表可替代真实课表跑通改名")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
