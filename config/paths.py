"""路径解析：全项目唯一真源（解决 C-7 硬编码用户名/盘符）。

设计要点
--------
1. BASE_DIR 由本文件位置推导（``config/paths.py`` 的上两级 = 项目根），
   因此整个 ``study`` 目录复制到任何盘符/用户名下都能直接跑。
2. 允许用环境变量 ``COURSE_NOTES_BASE_DIR`` 覆盖，便于把数据放到别的盘。
3. 课表候选、插件目录都不再写死用户目录。
4. 插件（清洗/分析提示词）优先用仓库内自带副本，TRAE 的安装目录只作兜底，
   避免「重装/移动 TRAE 后桌面链路就找不到 SKILL.md」。
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# 项目根：.../study
#   paths.py -> config/ -> 项目根
# --------------------------------------------------------------------------
_DEFAULT_BASE = Path(__file__).resolve().parent.parent

BASE_DIR = Path(os.getenv("COURSE_NOTES_BASE_DIR", _DEFAULT_BASE)).resolve()

# --------------------------------------------------------------------------
# 目录布局
# --------------------------------------------------------------------------
SOUNDS_DIR = BASE_DIR / "sounds"            # 输入录音
TXT_DIR = BASE_DIR / "txt"                  # 转录输出

# 输出分层（解决 C-8：Agent 与桌面各写各的，不再互相覆盖）
OUTPUTS_DIR = BASE_DIR / "course-notes" / "outputs"   # Agent / 手动链路产物（保持原位置不动）
OUTPUTS_DESKTOP_DIR = OUTPUTS_DIR / "desktop"          # 桌面程序产物，独立子目录

DATA_DIR = BASE_DIR / "data"                # 新建的统一数据目录
DESKTOP_DATA_DIR = BASE_DIR / "course-notes-desktop" / "data"   # 兼容旧位置

# 任务库位置
#   新位置 data/tasks.db 是目标位置；旧位置 course-notes-desktop/data/tasks.db 是历史遗留。
#   只有在旧库**确实含有任务行**时才继续沿用旧库（保护老用户数据），否则一律用新位置。
#   注意：这里必须查真实行数，不能像早期实现那样用「文件大小 > 0」冒充 ——
#   一个建过表但 0 行的库大小是 20480 字节，会被误判成「有数据」，
#   导致 DB_PATH 永远停在旧位置、新位置永不创建。
_OLD_DB = DESKTOP_DATA_DIR / "tasks.db"
_NEW_DB = DATA_DIR / "tasks.db"


def _sqlite_task_rows(db_file: Path) -> int:
    """返回该 sqlite 库里 tasks 表的行数；文件不存在/不是库/无该表都算 0。"""
    import sqlite3

    if not db_file.exists():
        return 0
    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return 0
    try:
        return int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


_old_rows = _sqlite_task_rows(_OLD_DB)
DB_PATH = _OLD_DB if _old_rows > 0 else _NEW_DB

# 供诊断：旧库实际有多少行、最终选了哪个库
DB_SOURCE = f"old({_old_rows} rows)" if _old_rows > 0 else "new"

# 插件提示词目录：仓库内副本优先
PLUGIN_DIR_CANDIDATES = [
    BASE_DIR / "course-notes" / "0.1.0",
    Path.home() / ".trae-cn" / "plugins" / "local" / "course-notes" / "0.1.0",
]


def resolve_plugin_dir() -> Path:
    """返回第一个存在的插件目录；都不存在时返回仓库内候选（便于报错时提示路径）。"""
    for cand in PLUGIN_DIR_CANDIDATES:
        if (cand / "skills").is_dir():
            return cand
    return PLUGIN_DIR_CANDIDATES[0]


PLUGIN_DIR = resolve_plugin_dir()

CLEANER_SKILL_MD = PLUGIN_DIR / "skills" / "transcript-cleaner" / "SKILL.md"
CLEANER_RULES_MD = PLUGIN_DIR / "skills" / "transcript-cleaner" / "references" / "cleaning-rules.md"
ANALYZER_SKILL_MD = PLUGIN_DIR / "skills" / "course-assessment-analyzer" / "SKILL.md"
ANALYZER_SCHEMA_MD = PLUGIN_DIR / "skills" / "course-assessment-analyzer" / "references" / "schema-v1.1.md"

# --------------------------------------------------------------------------
# 课表候选：只在 BASE_DIR 及其父/桌面下找，不再写死用户名
#
# 顺序即优先级：真实课表永远排在示例课表前面。
# 仓库自带的 课表.example.xls 是虚构数据，只为让 clone 的人能立刻跑通改名；
# 一旦你放入自己的 课表.xls，它就会被优先使用。
# --------------------------------------------------------------------------
SCHEDULE_CANDIDATES = [
    BASE_DIR / "课表.xls",
    BASE_DIR / "课表.xlsx",
    BASE_DIR / "课表.txt",
    BASE_DIR / "课表 .txt",
    BASE_DIR.parent / "课表 .txt",      # 旧习惯：放在桌面上
    BASE_DIR.parent / "课表.txt",
    BASE_DIR / "课表.example.xls",      # 仓库自带示例（虚构数据），优先级最低
]

# 运行中锁文件（解决 C-6：两个入口抢同一个 sounds/）
LOCK_FILE = BASE_DIR / ".course-notes.lock"

# 临时目录（本机 TEMP 曾出现不可写，统一兜底到项目内 .tmp）
TMP_DIR = BASE_DIR / ".tmp"


def find_schedule_file() -> Path | None:
    for p in SCHEDULE_CANDIDATES:
        if p.exists():
            return p
    return None


def ensure_dirs() -> None:
    """确保运行所需目录存在。"""
    for d in (SOUNDS_DIR, TXT_DIR, OUTPUTS_DESKTOP_DIR, DB_PATH.parent, TMP_DIR):
        d.mkdir(parents=True, exist_ok=True)
