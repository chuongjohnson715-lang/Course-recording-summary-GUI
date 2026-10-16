"""跨进程锁验证（C-6 的关键判据）。

用户级验证要求：锁必须在**两个独立进程**之间互斥，而不只是同进程内两个对象。
本脚本用 subprocess 真开第二个进程去抢同一个锁。

运行：
    python tests/test_lock.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SANDBOX = Path(tempfile.mkdtemp(prefix="cn_lock_"))
LOCK = _SANDBOX / "test.lock"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


HOLDER_SRC = '''
import sys, time
sys.path.insert(0, sys.argv[1])
from core.lock import FileLock

lock = FileLock(sys.argv[2], mode="holder")
if not lock.acquire():
    print("HOLDER-FAILED-TO-ACQUIRE")
    sys.exit(1)
print("HELD", flush=True)
time.sleep(float(sys.argv[3]))
lock.release()
print("RELEASED", flush=True)
'''

CHALLENGER_SRC = '''
import sys
sys.path.insert(0, sys.argv[1])
from core.lock import FileLock

lock = FileLock(sys.argv[2], mode="challenger")
got = lock.acquire()
print("ACQUIRED" if got else "REFUSED", flush=True)
if got:
    lock.release()
'''


def main() -> int:
    import shutil

    holder_py = _SANDBOX / "holder.py"
    chal_py = _SANDBOX / "challenger.py"
    holder_py.write_text(HOLDER_SRC, encoding="utf-8")
    chal_py.write_text(CHALLENGER_SRC, encoding="utf-8")

    print("=== 1. 第一个进程拿锁并持有 6 秒 ===")
    holder = subprocess.Popen(
        [sys.executable, "-u", str(holder_py), str(ROOT), str(LOCK), "6"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    first_line = holder.stdout.readline().strip()
    check("持有进程成功加锁", first_line == "HELD", f"-> {first_line!r}")

    print("=== 2. 第二个独立进程尝试抢同一把锁 ===")
    chal = subprocess.run(
        [sys.executable, "-u", str(chal_py), str(ROOT), str(LOCK)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    out = (chal.stdout or "").strip()
    check("第二个进程被拒绝", out == "REFUSED", f"-> {out!r} / {chal.stderr[:200]!r}")

    print("=== 3. 锁文件里记录了持有者信息 ===")
    info = LOCK.read_text(encoding="utf-8") if LOCK.exists() else ""
    check("锁文件含 pid", '"pid"' in info, f"-> {info[:120]!r}")

    print("=== 4. 持有者退出后，锁应可被接管 ===")
    holder.wait(timeout=30)
    time.sleep(0.5)
    chal2 = subprocess.run(
        [sys.executable, "-u", str(chal_py), str(ROOT), str(LOCK)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    out2 = (chal2.stdout or "").strip()
    check("释放后第二个进程能拿到", out2 == "ACQUIRED", f"-> {out2!r}")

    print("=== 5. 陈旧锁（持有者已死）应被自动接管 ===")
    LOCK.write_text('{"pid": 999999, "mode": "dead", "since": "x", "host": "y"}', encoding="utf-8")
    chal3 = subprocess.run(
        [sys.executable, "-u", str(chal_py), str(ROOT), str(LOCK)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    out3 = (chal3.stdout or "").strip()
    check("死进程留下的锁被接管", out3 == "ACQUIRED", f"-> {out3!r}")

    shutil.rmtree(_SANDBOX, ignore_errors=True)
    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[PASSED] 跨进程锁验证通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
