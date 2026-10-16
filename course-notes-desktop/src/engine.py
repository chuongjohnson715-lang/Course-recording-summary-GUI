"""后台处理引擎：扫描、改名、转录、清洗、分析、归档。"""
import time
import queue
import threading
from pathlib import Path

from . import db
from .cleaner import TranscriptCleaner
from .analyzer import CourseAnalyzer
from .notion_client import NotionArchiver
from .config import (
    SOUNDS_DIR,
    TXT_DIR,
    AUDIO_EXTS,
    MIN_FILE_SIZE,
    STABLE_SECONDS,
    POLL_INTERVAL_MS,
    LOCK_FILE,
    MAX_ATTEMPTS,
    RETRY_DELAY,
    RETRY_BACKOFF,
    DB_PATH,
    DB_SOURCE,
    Status,
    STEP_LABELS,
)
from .scheduler import find_schedule_file, load_schedule, rename_by_schedule
from .transcriber import Transcriber
from core.lock import FileLock
from core.retry import retry_call

# 处理循环连续异常多少次后放弃（避免持续性故障下变成空转刷日志的活锁）
MAX_CONSECUTIVE_FAILURES = 10


class EngineEvent:
    SCAN = "scan"
    TASK_UPDATE = "task_update"
    PROGRESS = "progress"
    LOG = "log"
    STATE = "state"


class ProcessingEngine:
    """在独立线程中运行，通过 event_queue 向 UI 发送事件。"""

    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._transcriber = Transcriber()
        self._cleaner: TranscriptCleaner | None = None
        self._analyzer: CourseAnalyzer | None = None
        self._notion: NotionArchiver | None = None
        self._tracker: dict[Path, dict] = {}
        self._schedule = {}
        self._schedule_path = None
        self._monitor_mode = False
        self._lock: FileLock | None = None
        self._consecutive_failures = 0

    @property
    def running(self) -> bool:
        return self._running

    def _emit(self, kind: str, **kwargs):
        self.event_queue.put({"kind": kind, **kwargs})

    def _load_schedule(self):
        """加载课表。课表损坏不应该杀死引擎，因此这里自带兜底。

        这是独立复核列出的触发路径之一：_load_schedule 曾在 _loop 的 try 之外调用，
        课表解析一旦抛异常，线程会静默死亡且不释放锁。
        这里改成：解析失败就退回空课表（只是不改名），引擎继续正常工作。
        """
        path = find_schedule_file()
        self._schedule_path = path
        if not path:
            self._schedule = {}
            self._emit(EngineEvent.LOG, message="未找到课表，将跳过改名")
            return
        try:
            self._schedule = load_schedule(path)
            self._emit(EngineEvent.LOG, message=f"已加载课表: {path.name}")
        except Exception as exc:  # noqa: BLE001
            self._schedule = {}
            self._emit(
                EngineEvent.LOG,
                message=(
                    f"课表解析失败（{type(exc).__name__}: {exc}），"
                    "本次将跳过改名，仅做转录。请检查课表文件格式。"
                ),
            )

    def _init_llm_tools(self):
        """延迟初始化 LLM 与 Notion 工具。"""
        try:
            if self._cleaner is None:
                self._cleaner = TranscriptCleaner()
        except Exception as exc:
            self._cleaner = None
            self._emit(EngineEvent.LOG, message=f"清洗模块初始化失败: {exc}")

        try:
            if self._analyzer is None:
                self._analyzer = CourseAnalyzer()
        except Exception as exc:
            self._analyzer = None
            self._emit(EngineEvent.LOG, message=f"分析模块初始化失败: {exc}")

        try:
            if self._notion is None:
                self._notion = NotionArchiver()
        except Exception as exc:
            self._notion = None
            self._emit(EngineEvent.LOG, message=f"Notion 模块初始化失败: {exc}")

    def _is_audio(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in AUDIO_EXTS

    def _is_stable(self, path: Path) -> bool:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        now = time.time()
        prev = self._tracker.get(path)
        if prev is None:
            self._tracker[path] = {"size": size, "changed_at": now}
            self._emit(EngineEvent.LOG, message=f"发现新文件: {path.name}，等待写入完成...")
            return False
        if size != prev["size"]:
            self._tracker[path] = {"size": size, "changed_at": now}
            return False
        return (now - prev["changed_at"]) >= STABLE_SECONDS

    def _process_task(self, task: dict):
        task_id = task["id"]
        original = Path(task["original_path"])
        current = Path(task["current_path"]) if task.get("current_path") else original

        try:
            # 0) 若文件不在当前路径，尝试用 original 重新定位
            if not current.exists() and original.exists():
                current = original

            # 等待文件稳定
            if not self._is_stable(current):
                db.update_task(task_id, status=Status.WAITING, step=STEP_LABELS[Status.WAITING])
                self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)
                return

            # 文件已稳定
            if current.stat().st_size < MIN_FILE_SIZE:
                raise ValueError("文件过小，跳过")

            # 1) 按课表改名
            db.update_task(task_id, status=Status.RENAME, step=STEP_LABELS[Status.RENAME])
            self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)
            final_path, course, date_str, matched = rename_by_schedule(current, self._schedule)
            if final_path != current:
                self._emit(EngineEvent.LOG, message=f"已改名: {current.name} -> {final_path.name}")
            elif not matched:
                self._emit(EngineEvent.LOG, message=f"未匹配到课程，保留原名: {current.name}")

            # 2) SenseVoice 转录
            db.update_task(
                task_id,
                status=Status.TRANSCRIBE,
                step=STEP_LABELS[Status.TRANSCRIBE],
                current_path=final_path,
                course_name=course,
                record_date=date_str,
            )
            self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)

            def on_progress(done, total):
                self._emit(
                    EngineEvent.PROGRESS,
                    task_id=task_id,
                    done=done,
                    total=total,
                )

            output_path = self._transcriber.transcribe(final_path, on_progress=on_progress)
            db.update_task(
                task_id,
                status=Status.CLEAN,
                step=STEP_LABELS[Status.CLEAN],
                current_path=final_path,
                output_path=output_path,
                course_name=course,
                record_date=date_str,
                error=None,
            )
            self._emit(EngineEvent.LOG, message=f"转录完成: {output_path.name}")
            self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)

            # 3) 清洗（C-11：瞬时网络故障自动重试，不再一次失败就永久 FAILED）
            self._init_llm_tools()
            if self._cleaner is None or not self._cleaner.is_configured():
                raise RuntimeError("清洗模块未就绪：请检查 .env 中的 OPENAI_API_KEY")
            cleaned_path = retry_call(
                lambda: self._cleaner.clean(output_path, course, date_str),
                attempts=MAX_ATTEMPTS,
                delay=RETRY_DELAY,
                backoff=RETRY_BACKOFF,
                on_retry=lambda n, exc: self._emit(
                    EngineEvent.LOG,
                    message=f"清洗第 {n} 次失败（{exc}），正在重试...",
                ),
            )
            db.update_task(
                task_id,
                status=Status.ANALYZE,
                step=STEP_LABELS[Status.ANALYZE],
                cleaned_path=cleaned_path,
            )
            self._emit(EngineEvent.LOG, message=f"清洗完成: {cleaned_path.name}")
            self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)

            # 4) 考核分析（同样自动重试）
            if self._analyzer is None or not self._analyzer.is_configured():
                raise RuntimeError("分析模块未就绪：请检查 .env 中的 OPENAI_API_KEY")
            analysis_path, summary_path = retry_call(
                lambda: self._analyzer.analyze(cleaned_path, course, date_str),
                attempts=MAX_ATTEMPTS,
                delay=RETRY_DELAY,
                backoff=RETRY_BACKOFF,
                on_retry=lambda n, exc: self._emit(
                    EngineEvent.LOG,
                    message=f"分析第 {n} 次失败（{exc}），正在重试...",
                ),
            )
            db.update_task(
                task_id,
                status=Status.NOTION,
                step=STEP_LABELS[Status.NOTION],
                analysis_path=analysis_path,
                summary_path=summary_path,
            )
            self._emit(EngineEvent.LOG, message=f"分析完成: {analysis_path.name}")
            self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)

            # 5) Notion 归档
            notion_page_id = None
            if self._notion and self._notion.is_configured():
                try:
                    notion_page_id = self._notion.archive(summary_path, course, date_str)
                    self._emit(EngineEvent.LOG, message=f"Notion 归档完成: {notion_page_id}")
                except Exception as exc:
                    self._emit(EngineEvent.LOG, message=f"Notion 归档失败（已保留本地文件）: {exc}")
            else:
                self._emit(EngineEvent.LOG, message="Notion 未配置，跳过归档")

            db.update_task(
                task_id,
                status=Status.DONE,
                step=STEP_LABELS[Status.DONE],
                notion_page_id=notion_page_id,
                error=None,
            )
            self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)

        except InterruptedError:
            db.update_task(task_id, status=Status.PENDING, step="已取消", error=None)
            self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)
        except Exception as exc:
            db.update_task(task_id, status=Status.FAILED, step="处理失败", error=str(exc))
            self._emit(EngineEvent.LOG, message=f"处理失败 [{original.name}]: {exc}")
            self._emit(EngineEvent.TASK_UPDATE, task_id=task_id)

    def _scan_new_files(self):
        """扫描 sounds/ 中未入库的音频文件。"""
        if not SOUNDS_DIR.exists():
            return
        existing_originals = {Path(t["original_path"]).resolve() for t in db.list_tasks()}
        for p in sorted(SOUNDS_DIR.iterdir()):
            if not self._is_audio(p):
                continue
            resolved = p.resolve()
            if resolved in existing_originals:
                continue
            task = db.get_or_create_task(p)
            self._emit(EngineEvent.TASK_UPDATE, task_id=task["id"])
            existing_originals.add(resolved)

    def _loop(self):
        self._consecutive_failures = 0

        try:
            self._load_schedule()
            self._emit(EngineEvent.LOG, message=f"任务库: {DB_PATH}（来源: {DB_SOURCE}）")
            self._emit(EngineEvent.STATE, running=True)

            while not self._stop_event.is_set():
                try:
                    # 扫描新文件
                    self._scan_new_files()
                    self._emit(EngineEvent.SCAN)

                    # 处理待处理/等待中的任务
                    tasks = db.get_pending_or_unfinished()
                    for task in tasks:
                        if self._stop_event.is_set():
                            break
                        self._process_task(task)

                    # 如果不在监控模式且没有待处理任务，自动结束
                    if not self._monitor_mode and not db.get_pending_or_unfinished():
                        self._emit(EngineEvent.LOG, message="队列已清空，自动结束处理")
                        break

                    # 本轮完整成功，清零连续失败计数
                    self._consecutive_failures = 0
                except Exception as exc:  # noqa: BLE001
                    # 单轮异常（sqlite 抖动、目录暂时不可读、课表损坏等）不应杀死线程：
                    # 过去这里没有兜底，异常会让线程静默死亡，而 _running 仍为 True、
                    # FileLock 也不释放，导致引擎永久无法重启。
                    self._consecutive_failures += 1
                    self._emit(
                        EngineEvent.LOG,
                        message=(
                            f"处理循环出现异常（第 {self._consecutive_failures} 次）: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    )
                    if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        self._emit(
                            EngineEvent.LOG,
                            message=(
                                f"连续 {self._consecutive_failures} 次异常，为避免空转已停止引擎。"
                                "请检查上面的错误原因后重新启动。"
                            ),
                        )
                        break
                    # 异常后短暂退避，避免异常风暴时疯狂刷日志
                    self._stop_event.wait(1.0)
                    continue

                self._stop_event.wait(POLL_INTERVAL_MS / 1000)
        finally:
            # 无论正常退出、break、异常还是被 stop()，都必须归位并释放锁
            self._running = False
            self._emit(EngineEvent.STATE, running=False)
            self._release_lock()

    def _release_lock(self) -> None:
        """释放 sounds/ 监控锁。"""
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    def start(self, monitor: bool = False):
        """启动后台处理线程。"""
        if self._running:
            return
        if monitor:
            # C-6：监控 sounds/ 需要独占锁，避免与命令行监控互相破坏
            lock = FileLock(LOCK_FILE, mode="desktop")
            if not lock.acquire():
                self._emit(
                    EngineEvent.LOG,
                    message=(
                        "已有另一个程序在监控 sounds/"
                        f"（{lock.describe_holder()}），本程序暂不监控以免冲突。"
                        "请先关闭那个程序。"
                    ),
                )
                return
            self._lock = lock
        self._stop_event.clear()
        self._transcriber.reset_cancel()
        self._monitor_mode = monitor
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """请求停止。"""
        if not self._running:
            return
        self._stop_event.set()
        self._transcriber.cancel()
        if self._thread:
            self._thread.join(timeout=2)
        self._running = False
        self._emit(EngineEvent.STATE, running=False)
        self._release_lock()
