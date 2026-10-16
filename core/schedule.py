"""课表解析 + 按课表改名（C-4 的唯一实现）。

历史背景：本逻辑曾在两处各写一遍 ——
  * sensevoice/watch_and_transcribe.py（178-239 行）
  * course-notes-desktop/src/scheduler.py（119-170 行）
两份逐行等价但细节漂移（一份会打印、一份多返回课程名）。

现在合并为本模块，并用 dry_run / verbose 两个开关同时覆盖两种调用方式：
  * 命令行入口：dry_run=False, verbose=True
  * 桌面程序：  dry_run=False, verbose=False，并取用返回的课程名/日期
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from config import paths
from config.settings import MAX_GAP_MINUTES, SEMESTER_START

WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

TAG_PATTERN = re.compile(r"<\|[^|]+\|>")                                  # SenseVoice 特殊标记
NAME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})")     # 20261008_100444
SLOT_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})~(\d{1,2}):(\d{2})")         # 08:00~09:50
WEEK_STR_RE = re.compile(r"([\d\s,，、\-]+)\s*周")                        # 1-4,8周


def find_schedule_file() -> Path | None:
    """按 config/paths.py 的候选顺序找课表文件。"""
    return paths.find_schedule_file()


def parse_weeks_str(s: str) -> set[int]:
    """把 '1-4,8' / '3-12' 之类的周次串解析为激活周号集合（1-based）。"""
    active: set[int] = set()
    for part in re.split(r"[,\s，、]+", s):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                active.update(range(int(a), int(b) + 1))
            except ValueError:
                continue
        elif part.isdigit():
            active.add(int(part))
    return active


def _parse_course_cell(cell: str) -> list[tuple[str, set[int] | None]]:
    """把一个格子里的多门课程解析为 [(课程名, 激活周集合|None)]。"""
    out: list[tuple[str, set[int] | None]] = []
    pending_name: str | None = None
    for raw in cell.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        mw = WEEK_STR_RE.search(ln)
        if mw and ";" in ln and pending_name:        # 教师/周次行，如 某教师;1-4,8周;1-2节
            out.append((pending_name, parse_weeks_str(mw.group(1))))
            pending_name = None
        elif "楼" in ln or "室" in ln or "线上" in ln:  # 教室/地点行，跳过
            continue
        else:
            pending_name = ln
    if pending_name:
        out.append((pending_name, None))
    return out


def load_schedule_xls(path: Path, verbose: bool = False) -> dict[int, list]:
    import xlrd

    wb = xlrd.open_workbook(str(path))
    sh = wb.sheet_by_index(0)

    # 表头第 3 行（index 2）给出 星期一~星期日 → 列号
    day_col: dict[int, int] = {}
    for c in range(1, sh.ncols):
        h = str(sh.cell_value(2, c)).strip()
        if h in WEEKDAY_NAMES:
            day_col[WEEKDAY_NAMES.index(h)] = c

    weekly: dict[int, list] = {wd: [] for wd in day_col}
    for r in range(3, sh.nrows):
        label = str(sh.cell_value(r, 0))
        tm = SLOT_TIME_RE.search(label)
        if not tm:
            continue
        start = int(tm.group(1)) * 60 + int(tm.group(2))
        end = int(tm.group(3)) * 60 + int(tm.group(4))
        for wd, col in day_col.items():
            cell = str(sh.cell_value(r, col))
            if not cell.strip():
                continue
            for course, weeks in _parse_course_cell(cell):
                weekly[wd].append((course, start, end, weeks))

    if verbose:
        total = sum(len(v) for v in weekly.values())
        print(f"  已解析 {path.name}：共 {len(day_col)} 天、{total} 门次课程")
    return weekly


def load_schedule(path: Path | None, verbose: bool = False) -> dict[int, list]:
    """解析课表。非 .xls 暂不支持，返回空表（不抛异常）。"""
    if path is None:
        return {}
    if path.suffix.lower() == ".xls":
        return load_schedule_xls(path, verbose=verbose)
    if verbose:
        print(f"  课表 {path.name} 不是 .xls 格式，暂不支持按周课表改名")
    return {}


def parse_recording_time(filename: str) -> tuple[int, ...] | None:
    """从录音文件名解析 (年,月,日,时,分,秒)，解析不出返回 None。"""
    m = NAME_RE.match(filename)
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def safe_name(name: str) -> str:
    """去掉文件名里的非法字符。"""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def fmt_time(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def semester_week(dt: date) -> int | None:
    """根据开学日计算录音日期处于第几周（1-based）；开学前返回 None。"""
    delta = (dt - datetime(*SEMESTER_START).date()).days
    if delta < 0:
        return None
    return delta // 7 + 1


def rename_by_schedule(
    audio_path: Path,
    weekly: dict[int, list],
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[Path, str | None, str | None, bool]:
    """根据录音时间查周课表重命名。

    返回 ``(最终路径, 课程名, 日期字符串, 是否匹配到课程)``。
    未匹配时原样返回入参路径，课程名为 None。

    ``dry_run=True`` 时只打印将要做的改名，不真正动文件。
    """
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    rec = parse_recording_time(audio_path.name)
    if rec is None:
        log(f"  文件名不含时间戳，跳过重命名: {audio_path.name}")
        return audio_path, None, None, False

    year, month, day, hour, minute, second = rec
    try:
        dt = date(year, month, day)
    except ValueError:
        log(f"  录音日期异常，跳过重命名: {audio_path.name}")
        return audio_path, None, None, False

    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    wno = semester_week(dt)
    weekday = dt.weekday()
    day_slots = weekly.get(weekday)
    if not day_slots:
        log(f"  {month}月{day}日（{WEEKDAY_NAMES[weekday]}）无课程安排，保留原名")
        return audio_path, None, date_str, False

    minute_of_day = hour * 60 + minute
    # 只在「当前激活周」的课程里匹配；算不出周次时按全部课程匹配
    if wno is not None:
        active = [s for s in day_slots if s[3] is None or wno in s[3]]
        if not active:
            log(f"  当前为第{wno}周，该时段课程均不在本周，保留原名")
            return audio_path, None, date_str, False
    else:
        active = day_slots

    best = None
    best_gap = None
    for course, start, end, _ in active:
        gap = 0 if start <= minute_of_day <= end else min(
            abs(minute_of_day - start), abs(minute_of_day - end)
        )
        if best_gap is None or gap < best_gap:
            best, best_gap = (course, start, end), gap

    if best is None or best_gap > MAX_GAP_MINUTES:
        log(f"  {month}月{day}日 {fmt_time(minute_of_day)} 未匹配到课程，保留原名")
        return audio_path, None, date_str, False

    course, start, end = best
    stamp = f"{year:04d}{month:02d}{day:02d}_{hour:02d}{minute:02d}{second:02d}"
    new_path = audio_path.with_name(f"{safe_name(course)}_{stamp}{audio_path.suffix}")

    if new_path == audio_path:
        return audio_path, course, date_str, True
    if new_path.exists():
        log(f"  目标文件名已存在，保留原名: {new_path.name}")
        return audio_path, course, date_str, True

    log(f"  匹配课程: {course}（{fmt_time(start)}~{fmt_time(end)}，第{wno}周）")
    if dry_run:
        log(f"  [DRY-RUN] 将重命名: {audio_path.name} -> {new_path.name}")
        return audio_path, course, date_str, True

    audio_path.rename(new_path)
    log(f"  已重命名: {audio_path.name} -> {new_path.name}")
    return new_path, course, date_str, True
