"""命令行监控入口（原 sensevoice/watch_and_transcribe.py）。

行为与旧脚本一致，但：
  * 改名/转录逻辑来自 core/（不再有第二份拷贝）
  * 启动时已在 sounds/ 的文件默认也会被处理（C-14 修复）
  * 抢 sounds/ 监控锁，避免与桌面程序互相破坏（C-6 修复）
  * 路径来自 config/paths.py，换机器不用改代码（C-7 修复）

用法：
    python entry/watch.py                 # 监控 sounds/ 新文件
    python entry/watch.py --process-existing   # 启动时把已有的也跑一遍
    python entry/watch.py --dry-run       # 只演示改名，不动文件
    python entry/watch.py --no-rename     # 只转录，不改名
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# --- 让 config/ 与 core/ 可被 import ---
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import paths, settings                    # noqa: E402
from core.lock import FileLock, LockError             # noqa: E402
from core.schedule import load_schedule, rename_by_schedule   # noqa: E402
from core.transcribe import default_model, transcribe_file    # noqa: E402


def is_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in settings.AUDIO_EXTS


def is_stable(path: Path, tracker: dict) -> bool:
    """文件大小连续 STABLE_SECONDS 秒不变，判定复制完成。"""
    try:
        size = path.stat().st_size
    except OSError:
        return False

    now = time.time()
    prev = tracker.get(path)
    if prev is None:
        tracker[path] = {"size": size, "changed_at": now}
        print(f"发现新文件: {path.name}（{size} 字节），等待写入完成...")
        return False

    if size != prev["size"]:
        tracker[path] = {"size": size, "changed_at": now}
        print(f"  文件大小变化: {path.name} -> {size} 字节，仍在复制中...")
        return False

    return (now - prev["changed_at"]) >= settings.STABLE_SECONDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sounds/ 录音监控 + 改名 + 转录")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要做的改名，不真正改")
    parser.add_argument("--no-rename", action="store_true", help="跳过改名，只做转录")
    parser.add_argument(
        "--process-existing",
        action="store_true",
        help="启动时把 sounds/ 中已存在的录音也处理一遍（默认行为见 settings.yaml）",
    )
    parser.add_argument("--once", action="store_true", help="扫一遍就退出，不常驻监控")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass

    paths.ensure_dirs()

    print(f"监控目录: {paths.SOUNDS_DIR}")
    print(f"输出目录: {paths.TXT_DIR}")

    # 课表
    schedule_path = paths.find_schedule_file()
    if schedule_path:
        weekly = load_schedule(schedule_path, verbose=True)
        print(f"课表文件: {schedule_path}")
    else:
        weekly = {}
        print("未找到课表文件，将不进行重命名（仅转录）")
        print(f"（查找过这些位置: {[str(p) for p in paths.SCHEDULE_CANDIDATES]}）")

    process_existing = args.process_existing or settings.PROCESS_EXISTING_ON_START
    if args.dry_run:
        print("DRY-RUN 模式：不会真正改文件名")

    # 抢锁：防止与桌面程序同时抢 sounds/
    lock = FileLock(paths.LOCK_FILE, mode="watch")
    if not lock.acquire():
        print("\n[拒绝启动] 已有另一个程序在监控 sounds/：")
        print(f"  {lock.describe_holder()}")
        print("请先关掉它（桌面程序或另一个监控窗口），然后重试。")
        return 2

    print(f"已获取监控锁: {paths.LOCK_FILE}")

    # 启动时已存在的文件：C-14 修复 —— 默认会处理，而不是静默忽略
    known: set[Path] = set()
    existing = [p.resolve() for p in sorted(paths.SOUNDS_DIR.iterdir()) if is_audio(p)]
    if existing and not process_existing:
        known.update(existing)
        print(f"启动时已存在 {len(existing)} 个音频，按配置视为已处理（不重复识别）")
    elif existing:
        print(f"启动时已存在 {len(existing)} 个音频，将一并处理")

    print(f"开始监控...（轮询 {settings.POLL_INTERVAL}s / 判定稳定 {settings.STABLE_SECONDS}s）")
    print("把录音文件拷入监控目录即可自动识别，按 Ctrl+C 退出。\n")

    model = None
    tracker: dict = {}

    try:
        while True:
            for p in sorted(paths.SOUNDS_DIR.iterdir()):
                if not is_audio(p):
                    continue
                rp = p.resolve()
                if rp in known:
                    continue
                if not is_stable(rp, tracker):
                    continue

                known.add(rp)
                tracker.pop(rp, None)

                if rp.stat().st_size < settings.MIN_FILE_SIZE:
                    print(f"文件过小，跳过: {rp.name}\n")
                    continue

                print(f"文件已复制完成: {rp.name}")

                # 1) 按课表改名
                final_path = rp
                if not args.no_rename:
                    final_path, course, date_str, matched = rename_by_schedule(
                        rp, weekly, dry_run=args.dry_run, verbose=True
                    )
                    known.add(final_path.resolve())
                    if not matched:
                        print("  （未匹配到课程，保留原名）")

                # 2) 懒加载模型
                if model is None:
                    print("正在加载 SenseVoice 模型（首次较慢）...")
                    model = default_model()
                    print("模型加载完成。\n")

                # 3) 转录
                print(f"=== 开始识别: {final_path.name} ===")
                try:
                    out_path = transcribe_file(final_path, model=model, verbose=True)
                    print(f"完成，结果已保存: {out_path}\n")
                except Exception as exc:  # noqa: BLE001 - 单文件失败不该拖垮整个监控
                    print(f"[失败] {final_path.name}: {exc}\n")

            if args.once:
                print("--once 指定，扫描结束，退出。")
                break

            time.sleep(settings.POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n已停止监控。")
    finally:
        lock.release()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
