"""SQLite 任务持久化。"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

from .config import DB_PATH


def _ensure_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _column_exists(conn: sqlite3.Connection, col: str) -> bool:
    cur = conn.execute("PRAGMA table_info(tasks)")
    return any(row["name"] == col for row in cur.fetchall())


def init_db():
    """初始化数据库表。"""
    _ensure_dir()
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT NOT NULL UNIQUE,
                current_path TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                step TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                output_path TEXT,
                cleaned_path TEXT,
                analysis_path TEXT,
                summary_path TEXT,
                notion_page_id TEXT,
                course_name TEXT,
                record_date TEXT,
                meta TEXT
            )
            """
        )
        # 兼容 V1 旧表：补充新列
        for col in ("cleaned_path", "analysis_path", "summary_path", "notion_page_id"):
            if not _column_exists(conn, col):
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)
            """
        )


@contextmanager
def _connect():
    # timeout：另一个进程/线程正在写时等待而不是立刻抛 "database is locked"
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        # WAL：允许「一个写 + 多个读」并发，桌面引擎线程与 UI 线程同时访问才稳。
        # 设不上（例如放在网络盘）也不致命，忽略即可。
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
        except sqlite3.Error:
            pass
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def row_to_dict(row: sqlite3.Row) -> dict:
    # 注意：sqlite3.Row 没有 .get()，旧实现用 row.get("meta") 会在读取任何
    # 已存在任务时抛 AttributeError —— 这也是 tasks 表一直是 0 行的原因之一。
    data = {k: row[k] for k in row.keys()}
    raw_meta = data.get("meta")
    try:
        data["meta"] = json.loads(raw_meta) if raw_meta else {}
    except (TypeError, ValueError):
        data["meta"] = {}
    return data


def get_or_create_task(path: Path) -> dict:
    """根据原始路径获取任务；不存在则创建 pending 任务。

    注意：这里**不能**在 `with _connect()` 里递归调用自己 ——
    旧实现就是那么写的，外层写事务还没提交、内层又去开一个新连接读同一张表，
    必然 "database is locked"（每次新建任务都会踩）。现在改成单连接内完成。
    """
    resolved = str(path.resolve())
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE original_path = ?",
            (resolved,),
        ).fetchone()
        if row:
            return row_to_dict(row)

        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO tasks
                (original_path, current_path, status, created_at, updated_at, meta)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (resolved, resolved, "pending", now, now, "{}"),
        )
        row = conn.execute(
            "SELECT * FROM tasks WHERE original_path = ?",
            (resolved,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"任务创建失败: {resolved}")
        return row_to_dict(row)


def list_tasks(status: str | None = None) -> list[dict]:
    """列出任务，可按状态过滤，按创建时间倒序。"""
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            ).fetchall()
        return [row_to_dict(r) for r in rows]


# 哨兵：用来区分「没传这个参数」与「显式传 None 以清空该字段」。
# 旧实现用 None 同时表示这两种含义，导致失败重试成功后的任务仍残留上次的错误文本。
_UNSET: object = object()


def update_task(
    task_id: int,
    *,
    status: str | None = None,
    current_path: Path | str | None = None,
    output_path: Path | str | None = None,
    cleaned_path: Path | str | None = None,
    analysis_path: Path | str | None = None,
    summary_path: Path | str | None = None,
    notion_page_id: str | None = None,
    step: str | None = None,
    error: str | None | object = _UNSET,
    course_name: str | None = None,
    record_date: str | None = None,
    meta: dict | None = None,
) -> dict:
    """更新任务字段。"""
    with _connect() as conn:
        fields = ["updated_at = ?"]
        values = [_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
            if status in ("done", "failed"):
                fields.append("finished_at = ?")
                values.append(_now())
        if current_path is not None:
            fields.append("current_path = ?")
            values.append(str(Path(current_path).resolve()))
        if output_path is not None:
            fields.append("output_path = ?")
            values.append(str(Path(output_path)) if output_path else None)
        if cleaned_path is not None:
            fields.append("cleaned_path = ?")
            values.append(str(Path(cleaned_path)) if cleaned_path else None)
        if analysis_path is not None:
            fields.append("analysis_path = ?")
            values.append(str(Path(analysis_path)) if analysis_path else None)
        if summary_path is not None:
            fields.append("summary_path = ?")
            values.append(str(Path(summary_path)) if summary_path else None)
        if notion_page_id is not None:
            fields.append("notion_page_id = ?")
            values.append(notion_page_id)
        if step is not None:
            fields.append("step = ?")
            values.append(step)
        if error is not _UNSET:
            # 显式传 error=None 表示「清空错误」；完全不传则不动该字段
            fields.append("error = ?")
            values.append(error)
        if course_name is not None:
            fields.append("course_name = ?")
            values.append(course_name)
        if record_date is not None:
            fields.append("record_date = ?")
            values.append(record_date)
        if meta is not None:
            fields.append("meta = ?")
            values.append(json.dumps(meta, ensure_ascii=False))

        values.append(task_id)
        sql = f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?"
        conn.execute(sql, values)
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return row_to_dict(row)


def get_task_by_id(task_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return row_to_dict(row) if row else None


def get_pending_or_unfinished() -> list[dict]:
    """获取待处理或未完成的任务（启动时扫描用）。"""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status NOT IN ('done')
            ORDER BY created_at ASC
            """
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def stats() -> dict:
    """统计各状态数量。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
        ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        today = datetime.now().strftime("%Y-%m-%d")
        done_today = conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'done' AND date(finished_at) = ?",
            (today,),
        ).fetchone()["cnt"]
        return {
            "pending": counts.get("pending", 0),
            "waiting": counts.get("waiting", 0),
            "processing": (
                counts.get("rename", 0)
                + counts.get("transcribe", 0)
                + counts.get("clean", 0)
                + counts.get("analyze", 0)
                + counts.get("notion", 0)
            ),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "done_today": done_today,
        }
