"""运行中互斥锁（解决 C-6：两个入口同时抢 sounds/）。

背景：命令行监控（entry/watch.py）与桌面引擎都会扫描同一个 sounds/、
都会执行「改名 + 转录」。同时运行会出现：改名与转录交错、txt/ 产物互相覆盖、
Notion 重复归档。

做法：谁要监控 sounds/，谁先抢一个锁文件。抢不到就明确报错退出，
而不是两个进程闷头互相破坏。锁里写入 pid，进程已死则视为陈旧锁自动接管。

用法::

    with FileLock(paths.LOCK_FILE, mode="watch") as lock:
        lock.ensure_acquired()      # 抢不到 -> LockError
        ...监控循环...

    # 或者非阻塞尝试：
    lock = FileLock(paths.LOCK_FILE)
    if not lock.acquire():
        print(lock.describe_holder())
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


class LockError(RuntimeError):
    """锁被别的进程占用。"""


def _pid_alive(pid: int) -> bool:
    """判断进程是否还活着（Windows 优先，其他平台退化用 os.kill）。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class FileLock:
    """基于「独占创建文件」的跨进程锁。"""

    def __init__(self, path: Path, mode: str = "generic") -> None:
        self.path = Path(path)
        self.mode = mode
        self._held = False

    # ------------------------------------------------------------------
    def _read_info(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 锁文件损坏时按陈旧处理
            return {}

    def describe_holder(self) -> str:
        info = self._read_info()
        if not info:
            return "另一个进程"
        return (
            f"pid={info.get('pid')} mode={info.get('mode')} "
            f"since={info.get('since')} host={info.get('host')}"
        )

    # ------------------------------------------------------------------
    def acquire(self) -> bool:
        """尝试加锁。成功返回 True；被占用返回 False。"""
        if self._held:
            return True

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "mode": self.mode,
                "since": datetime.now().isoformat(timespec="seconds"),
                "host": os.environ.get("COMPUTERNAME", "?"),
            },
            ensure_ascii=False,
        )

        for _ in range(2):
            try:
                # O_EXCL：文件已存在就失败，天然原子
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                info = self._read_info()
                holder_pid = int(info.get("pid") or 0)
                if holder_pid and not _pid_alive(holder_pid):
                    # 持有者已死（上次崩溃/强杀），清理陈旧锁后重试一次
                    self._unlink_quietly()
                    continue
                return False
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                self._held = True
                return True
        return False

    def release(self) -> None:
        if self._held:
            self._unlink_quietly()
            self._held = False

    def _unlink_quietly(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def ensure_acquired(self) -> None:
        if not self.acquire():
            raise LockError(
                f"已有另一个程序正在监控 sounds/（{self.describe_holder()}）。\n"
                f"请先关闭那个程序，或确认它已退出后删除锁文件：\n  {self.path}"
            )

    # ------------------------------------------------------------------
    @property
    def held(self) -> bool:
        return self._held

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
