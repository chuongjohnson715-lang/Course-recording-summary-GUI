"""兼容层：课表解析/改名已合并到 core/schedule.py（C-4）。

保留同名函数，内部全部转发到 core，避免任何调用点失效。
新代码请直接 ``from core import schedule``。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.schedule import (                      # noqa: E402,F401
    WEEKDAY_NAMES,
    NAME_RE,
    SLOT_TIME_RE,
    WEEK_STR_RE,
    find_schedule_file,
    parse_weeks_str,
    _parse_course_cell,
    load_schedule_xls,
    load_schedule,
    parse_recording_time,
    safe_name,
    fmt_time,
    semester_week,
)


def rename_by_schedule(audio_path, weekly, *, dry_run: bool = False, verbose: bool = False):
    """转发到 core.schedule.rename_by_schedule。

    返回 4 元组 ``(最终路径, 课程名, 日期字符串, 是否匹配到课程)``，
    与 core 的契约一致；调用方（如 engine.py）按 4 个值解包。
    """
    from core.schedule import rename_by_schedule as _impl

    return _impl(audio_path, weekly, dry_run=dry_run, verbose=verbose)
