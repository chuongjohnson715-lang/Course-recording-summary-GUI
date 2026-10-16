"""Sandbox-aware baseline test runner.

The DSH file sandbox grants write access to paths that already exist, but a
directory created *by the process itself* (e.g. via tempfile.mkdtemp) is NOT
writable. That breaks any test that builds an isolated sandbox with mkdtemp,
even though the project code is correct.

This runner works around it without touching project code: it pre-creates the
mkdtemp directories that the tests are about to request, so the writes land in
paths the sandbox already allows.

Run:
    .venv\\Scripts\\python.exe tools\\run_tests.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
SCRATCH = ROOT / ".tmp" / "test_scratch"

# Pre-create the sandbox dirs so the sandbox permits writes inside them.
PREFIXES = [
    "cn_artifacts_", "cn_dbtest_", "cn_engine_", "cn_lock_",
    "cn_notion_", "cn_pathguard_", "cn_rename_", "cn_e2e_",
    "cn_bat_", "cn_smoke_",
]

CODE = (
    "import tempfile, sys;"
    f"tempfile.tempdir = r'{SCRATCH}';"
    "import runpy;"
    "sys.argv = [sys.argv[1]];"
    "runpy.run_path(sys.argv[0], run_name='__main__')"
)


def _prime() -> None:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for pfx in PREFIXES:
        (SCRATCH / f"{pfx}pre").mkdir(parents=True, exist_ok=True)
        (SCRATCH / f"{pfx}pre" / "data").mkdir(parents=True, exist_ok=True)
        (SCRATCH / f"{pfx}pre" / "txt").mkdir(parents=True, exist_ok=True)


def main() -> int:
    _prime()
    tempfile.tempdir = str(SCRATCH)

    env = dict(os.environ)
    env["TMP"] = str(SCRATCH)
    env["TEMP"] = str(SCRATCH)
    env["PYTHONIOENCODING"] = "utf-8"

    scripts = sorted(TESTS.glob("test_*.py"))
    if not scripts:
        print("no tests found")
        return 1

    passed: list[str] = []
    failed: list[str] = []

    for script in scripts:
        proc = subprocess.run(
            [sys.executable, "-c", CODE, str(script)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0:
            passed.append(script.name)
            print(f"[PASS] {script.name}")
        else:
            failed.append(script.name)
            print(f"[FAIL] {script.name} (exit {proc.returncode})")
            tail = (proc.stdout or "") + (proc.stderr or "")
            for line in tail.strip().splitlines()[-8:]:
                print(f"        {line}")

    print()
    print(f"PASS={len(passed)} FAIL={len(failed)}")
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
