"""Direct logic check that does NOT need mkdtemp (sandbox-friendly).

The project's own tests build isolated sandboxes with tempfile.mkdtemp(), and
the DSH sandbox denies writes inside directories created by the process, so six
of them cannot run here. This script exercises the same core behaviours using
the repo's real workspace layout instead, to show the code itself is sound.

Run:
    .venv\\Scripts\\python.exe tools\\selfcheck.py
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Use a writable, already-existing directory as the project base.
BASE = ROOT / ".tmp" / "selfcheck"
(BASE / "data").mkdir(parents=True, exist_ok=True)
(BASE / "txt").mkdir(parents=True, exist_ok=True)
(BASE / "course-notes" / "outputs" / "desktop").mkdir(parents=True, exist_ok=True)
(BASE / "course-notes-desktop" / "data").mkdir(parents=True, exist_ok=True)

os.environ["COURSE_NOTES_BASE_DIR"] = str(BASE)

for p in (str(ROOT / "course-notes-desktop"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

results: list[tuple[str, bool, str]] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    results.append((label, cond, detail))


# ---- 1. config/paths.py resolves from file location, not hardcoded user ----
paths = importlib.import_module("config.paths")
check("paths.BASE_DIR honours COURSE_NOTES_BASE_DIR", paths.BASE_DIR == BASE.resolve(),
      f"got {paths.BASE_DIR}")
check("SOUNDS_DIR/TXT_DIR derived from BASE_DIR",
      paths.SOUNDS_DIR == BASE / "sounds" and paths.TXT_DIR == BASE / "txt")
check("no hardcoded C:\\Users\\<user> in paths.py",
      "Users\\\\" not in Path(paths.__file__).read_text(encoding="utf-8"))

# ---- 2. schedule loader survives a missing timetable (no crash) ----
sched = importlib.import_module("core.schedule")
check("find_schedule_file returns None when no timetable present",
      paths.find_schedule_file() is None)

# ---- 3. db layer: init + insert + retry-clears-error (the 3 real bugs) ----
db = importlib.import_module("src.db")
db.init_db()
check("db.init_db created schema", db.DB_PATH.exists(), str(db.DB_PATH))

audio = BASE / "sounds" / "selfcheck_audio.m4a"
audio.parent.mkdir(parents=True, exist_ok=True)
audio.write_bytes(b"not-real-audio")

task = db.get_or_create_task(audio)
task_id = int(task["id"])
check("get_or_create_task returned a row without self-deadlock", bool(task_id))

again = db.get_or_create_task(audio)
check("get_or_create_task is idempotent", int(again["id"]) == task_id)

db.update_task(task_id, status="failed", error="boom")
row_failed = db.get_task_by_id(task_id)
check("failed status stored the error",
      (row_failed.get("error") or "").strip() == "boom",
      f"error={row_failed.get('error')!r}")

# The real regression: a retry that succeeds must not leave the old error text.
db.update_task(task_id, status="done", error=None)
row_done = db.get_task_by_id(task_id)
check("marking done clears stale error after a retry",
      not (row_done.get("error") or "").strip(),
      f"error={row_done.get('error')!r}")

check("row_to_dict works on sqlite3.Row (no AttributeError)", isinstance(row_done, dict))
check("stats() runs", isinstance(db.stats(), dict))

# ---- 4. plugin prompt files ship inside the repo (portability) ----
check("cleaner SKILL.md resolves inside repo",
      paths.CLEANER_SKILL_MD.exists(), str(paths.CLEANER_SKILL_MD))
check("analyzer SKILL.md resolves inside repo",
      paths.ANALYZER_SKILL_MD.exists(), str(paths.ANALYZER_SKILL_MD))

# ---- 5. lock module imports and exposes the API ----
lock = importlib.import_module("core.lock")
check("core.lock exposes FileLock/LockError",
      hasattr(lock, "FileLock") and hasattr(lock, "LockError"))

# ---- 6. .env-driven config degrades gracefully with no key ----
cfg = importlib.import_module("src.config")
check("config exposes credential names", hasattr(cfg, "OPENAI_API_KEY")
      and hasattr(cfg, "NOTION_TOKEN"))

# ---- report ----
failed = 0
for label, ok, detail in results:
    if ok:
        print(f"  [OK]   {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label} {detail}")

print()
print(f"selfcheck: {len(results) - failed}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
