"""引擎抗崩测试：处理循环出现异常后必须能自愈并可重启。

背景（独立复核发现的高危缺陷）：
原 ``ProcessingEngine._loop`` 没有 try/finally。循环体一旦抛异常，
工作线程静默死亡，但：
  * ``self._running`` 仍为 True
  * 不发 STATE(running=False) 事件
  * FileLock 不释放（占住 sounds/ 监控权，连 启动监控.bat 也起不来）
  * ``start()`` 开头的 ``if self._running: return`` 让引擎**永久无法重启**

本测试用故障注入证明修复有效：注入 N 次异常后，引擎应当
自己收尾（状态归位 + 释放锁），且用户再次 ``start()`` 能真正重新跑起来。

在隔离沙箱中运行，不碰真实 tasks.db / sounds/ / 锁文件。

运行：
    python tests/test_engine_resilience.py
"""
from __future__ import annotations

import os
import queue
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "course-notes-desktop"

_SANDBOX = Path(tempfile.mkdtemp(prefix="cn_engine_"))
os.environ["COURSE_NOTES_BASE_DIR"] = str(_SANDBOX)

for p in (str(DESKTOP), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


def drain(q: queue.Queue) -> list[dict]:
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            return events


def wait_until(pred, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def main() -> int:
    import shutil

    from config import paths
    from src import db
    from src.engine import EngineEvent, ProcessingEngine

    db.init_db()
    (paths.SOUNDS_DIR).mkdir(parents=True, exist_ok=True)

    print(f"隔离沙箱: {_SANDBOX}")
    print(f"锁文件:   {paths.LOCK_FILE}")

    # ---------------------------------------------------------------
    print("\n=== 1. 注入异常：线程不得静默死亡，必须收尾并释放锁 ===")
    q: queue.Queue = queue.Queue()
    engine = ProcessingEngine(q)
    engine.start(monitor=True)
    time.sleep(0.4)

    check("启动后处于运行中", engine.running is True)
    check("启动后锁文件存在", paths.LOCK_FILE.exists())

    # 故障注入：让扫描每轮都抛异常（模拟 sqlite 抖动 / 目录不可读）
    def boom() -> None:
        raise RuntimeError("injected failure")

    engine._scan_new_files = boom  # type: ignore[method-assign]

    # 引擎应在连续 10 次失败后自行停止；最多等 20 秒
    stopped = wait_until(lambda: not engine.running, timeout=20)
    check("异常后引擎自行停止（未静默死亡）", stopped, f"-> running={engine.running}")
    check("线程已退出", engine._thread is not None and not engine._thread.is_alive())
    check("锁文件已释放", not paths.LOCK_FILE.exists(), f"-> {paths.LOCK_FILE}")

    events = drain(q)
    state_events = [e for e in events if e.get("kind") == EngineEvent.STATE]
    check("发出了 STATE(running=False) 事件",
          any(e.get("running") is False for e in state_events),
          f"-> {state_events}")
    log_msgs = [e.get("message", "") for e in events if e.get("kind") == EngineEvent.LOG]
    check("日志里报告了连续异常",
          any("连续" in m for m in log_msgs),
          f"-> {log_msgs[-3:]}")

    # ---------------------------------------------------------------
    print("\n=== 2. 修复的意义：异常后必须能再次启动 ===")
    old_thread = engine._thread
    engine._scan_new_files = type(engine)._scan_new_files.__get__(engine)  # 恢复真实实现
    engine.start(monitor=True)
    time.sleep(0.4)

    check("第二次 start() 真的启动了（旧代码会静默 no-op）",
          engine.running is True, f"-> running={engine.running}")
    check("创建了新的工作线程", engine._thread is not old_thread)
    check("第二次启动重新拿到了锁", paths.LOCK_FILE.exists())
    drain(q)

    # ---------------------------------------------------------------
    print("\n=== 3. 自愈后功能仍正常：能扫描到新文件 ===")
    audio = paths.SOUNDS_DIR / "20261010_235959.m4a"
    audio.write_bytes(b"x" * 2048)
    saw_task = False
    deadline = time.time() + 15
    while time.time() < deadline:
        for e in drain(q):
            if e.get("kind") == EngineEvent.TASK_UPDATE:
                saw_task = True
        if saw_task:
            break
        time.sleep(0.2)
    check("重启后能扫描并建任务", saw_task)

    print("\n=== 4. 正常停止也要释放锁 ===")
    engine.stop()
    time.sleep(0.3)
    check("stop() 后 running=False", engine.running is False)
    check("stop() 后锁已释放", not paths.LOCK_FILE.exists())
    check("stop() 后线程已退出", engine._thread is not None and not engine._thread.is_alive())

    # ---------------------------------------------------------------
    print("\n=== 5. 课表损坏也不得杀死引擎（复核列出的触发路径之一）===")
    sched = paths.BASE_DIR / "课表.xls"
    sched_backup = sched.read_bytes() if sched.exists() else None
    try:
        # 让引擎解析一个损坏的课表
        sched.write_bytes(b"this is definitely not a valid xls file")
        q2: queue.Queue = queue.Queue()
        engine2 = ProcessingEngine(q2)
        engine2.start(monitor=True)
        time.sleep(1.2)

        alive = engine2.running is True
        check("课表损坏后引擎仍在运行（不静默死亡）", alive,
              f"-> running={engine2.running}")
        check("课表损坏后锁仍由引擎持有（进程还活着）", paths.LOCK_FILE.exists())
        msgs = [e.get("message", "") for e in drain(q2) if e.get("kind") == EngineEvent.LOG]
        check("日志里说明了课表解析失败",
              any("课表解析失败" in m for m in msgs), f"-> {msgs[-2:]}")

        engine2.stop()
        time.sleep(0.3)
        check("停止后锁已释放", not paths.LOCK_FILE.exists())
    finally:
        if sched_backup is not None:
            sched.write_bytes(sched_backup)

    shutil.rmtree(_SANDBOX, ignore_errors=True)
    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[PASSED] 引擎异常自愈与重启验证通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
