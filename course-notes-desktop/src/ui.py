"""Tkinter 四区域 UI。"""
import os
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from . import db
from .config import SOUNDS_DIR, TXT_DIR, Status, STEP_LABELS


# 状态颜色与标签
STATUS_STYLES = {
    Status.PENDING: ("待处理", "#6b7280"),
    Status.WAITING: ("等待中", "#3b82f6"),
    Status.RENAME: ("改名中", "#f59e0b"),
    Status.TRANSCRIBE: ("转录中", "#0d9488"),
    Status.CLEAN: ("清洗中", "#8b5cf6"),
    Status.ANALYZE: ("分析中", "#6366f1"),
    Status.NOTION: ("归档中", "#ec4899"),
    Status.DONE: ("已完成", "#10b981"),
    Status.FAILED: ("失败", "#ef4444"),
}


class App(ttk.Frame):
    def __init__(self, master: tk.Tk, engine):
        super().__init__(master)
        self.master = master
        self.engine = engine
        self.event_queue = engine.event_queue
        self._polling_id = None

        self._build_styles()
        self._build_layout()
        self._refresh_stats()
        self._refresh_task_list()
        self._start_polling()

    def _build_styles(self):
        style = ttk.Style(self.master)
        style.theme_use("clam")

        # 字体
        self.master.option_add("*Font", ("Microsoft YaHei UI", 10))

        # 主色
        style.configure("Primary.TButton", background="#0d9488", foreground="white")
        style.map("Primary.TButton", background=[("active", "#0f766e")])
        style.configure("Danger.TButton", background="#ef4444", foreground="white")
        style.map("Danger.TButton", background=[("active", "#b91c1c")])

        # 卡片框架
        style.configure("Card.TFrame", background="white")
        style.configure("CardTitle.TLabel", background="white", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("CardBody.TLabel", background="white", font=("Microsoft YaHei UI", 10))
        style.configure("Kpi.TLabel", background="white", font=("Microsoft YaHei UI", 28, "bold"))

    def _card(self, parent, title: str, row: int = None, column: int = None) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=12)
        if row is not None:
            frame.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        else:
            frame.pack(fill="both", expand=True, padx=8, pady=8)
        title_lbl = ttk.Label(frame, text=title, style="CardTitle.TLabel")
        title_lbl.pack(anchor="w", pady=(0, 8))
        return frame

    def _build_layout(self):
        self.master.title("课堂笔记助手 · Course Notes Assistant")
        self.master.geometry("1200x800")
        self.master.configure(bg="#f3f4f6")

        self.pack(fill="both", expand=True)
        self.configure(style="Card.TFrame")

        # 顶部标题栏
        header = ttk.Frame(self, padding="12 8", style="Card.TFrame")
        header.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(
            header,
            text="课堂笔记助手   Course Notes Assistant",
            style="CardTitle.TLabel",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(side="left")
        self.status_var = tk.StringVar(value="就绪")
        self.status_dot = tk.Label(header, text="●", fg="#6b7280", bg="white", font=("Microsoft YaHei UI", 12))
        self.status_dot.pack(side="right", padx=(0, 4))
        ttk.Label(header, textvariable=self.status_var, style="CardBody.TLabel").pack(side="right")

        # 主体：左侧边栏 + 右侧内容
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # 左侧：任务控制
        self._build_task_control(body)
        # 右侧：三栏
        self._build_right_panels(body)

    def _build_task_control(self, parent):
        sidebar = self._card(parent, "任务控制", row=0, column=0)
        sidebar.configure(width=260)
        sidebar.grid_propagate(False)

        # 开始处理
        self.start_btn = tk.Button(
            sidebar,
            text="▶  开始处理",
            bg="#0d9488",
            fg="white",
            activebackground="#0f766e",
            activeforeground="white",
            font=("Microsoft YaHei UI", 12, "bold"),
            relief="flat",
            cursor="hand2",
            command=self._on_start,
        )
        self.start_btn.pack(fill="x", pady=(0, 10), ipady=8)

        # 持续监控
        self.monitor_var = tk.BooleanVar(value=False)
        self.monitor_btn = tk.Button(
            sidebar,
            text="持续监控：关",
            bg="#e5e7eb",
            fg="#374151",
            activebackground="#d1d5db",
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            cursor="hand2",
            command=self._on_toggle_monitor,
        )
        self.monitor_btn.pack(fill="x", pady=(0, 10), ipady=6)

        # 停止
        self.stop_btn = tk.Button(
            sidebar,
            text="■  停止",
            bg="#ef4444",
            fg="white",
            activebackground="#b91c1c",
            activeforeground="white",
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            cursor="hand2",
            command=self._on_stop,
        )
        self.stop_btn.pack(fill="x", pady=(0, 20), ipady=6)

        # KPI
        kpi_frame = ttk.Frame(sidebar, style="Card.TFrame")
        kpi_frame.pack(fill="x", pady=(0, 20))
        kpi_frame.columnconfigure(0, weight=1)
        kpi_frame.columnconfigure(1, weight=1)

        self.pending_var = tk.StringVar(value="0")
        ttk.Label(kpi_frame, text="待处理录音", style="CardBody.TLabel").grid(row=0, column=0)
        ttk.Label(kpi_frame, textvariable=self.pending_var, style="Kpi.TLabel").grid(row=1, column=0)

        self.done_var = tk.StringVar(value="0")
        ttk.Label(kpi_frame, text="今日已完成", style="CardBody.TLabel").grid(row=0, column=1)
        ttk.Label(kpi_frame, textvariable=self.done_var, style="Kpi.TLabel").grid(row=1, column=1)

        # 打开目录
        open_btn = tk.Button(
            sidebar,
            text="打开录音目录",
            bg="white",
            fg="#0d9488",
            activebackground="#f0fdfa",
            font=("Microsoft YaHei UI", 10),
            relief="solid",
            cursor="hand2",
            command=lambda: os.startfile(str(SOUNDS_DIR)),
        )
        open_btn.pack(fill="x", pady=(0, 10), ipady=6)

        self.history_btn = tk.Button(
            sidebar,
            text="处理历史",
            bg="white",
            fg="#374151",
            activebackground="#f3f4f6",
            font=("Microsoft YaHei UI", 10),
            relief="solid",
            cursor="hand2",
            command=lambda: os.startfile(str(TXT_DIR)),
        )
        self.history_btn.pack(fill="x", pady=(0, 10), ipady=6)

    def _build_right_panels(self, parent):
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        # 文件队列
        queue_card = self._card(right, "文件队列", row=0, column=0)
        self._build_queue_panel(queue_card)

        # 处理进度
        progress_card = self._card(right, "当前任务", row=1, column=0)
        self._build_progress_panel(progress_card)

        # 处理结果
        results_card = self._card(right, "处理结果", row=2, column=0)
        self._build_results_panel(results_card)

    def _build_queue_panel(self, parent):
        # 标签过滤
        tabs = ttk.Frame(parent, style="Card.TFrame")
        tabs.pack(fill="x", pady=(0, 8))
        self.queue_filter = tk.StringVar(value="all")
        for label, value in [
            ("全部", "all"),
            ("待处理", "pending"),
            ("处理中", "processing"),
            ("已完成", "done"),
            ("失败", "failed"),
        ]:
            rb = tk.Radiobutton(
                tabs,
                text=label,
                variable=self.queue_filter,
                value=value,
                bg="white",
                selectcolor="#0d9488",
                fg="#374151",
                activebackground="white",
                indicatoron=False,
                cursor="hand2",
                command=self._refresh_task_list,
            )
            rb.pack(side="left", padx=2)

        columns = ("filename", "course", "status", "date")
        self.tree = ttk.Treeview(
            parent,
            columns=columns,
            show="headings",
            height=6,
        )
        self.tree.heading("filename", text="文件名")
        self.tree.heading("course", text="课程")
        self.tree.heading("status", text="状态")
        self.tree.heading("date", text="日期")
        self.tree.column("filename", width=260)
        self.tree.column("course", width=140)
        self.tree.column("status", width=80)
        self.tree.column("date", width=100)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_task_select)

    def _build_progress_panel(self, parent):
        self.current_task_var = tk.StringVar(value="当前任务：—")
        self.current_step_var = tk.StringVar(value="—")
        ttk.Label(parent, textvariable=self.current_task_var, style="CardTitle.TLabel").pack(anchor="w")

        self.step_frame = ttk.Frame(parent, style="Card.TFrame")
        self.step_frame.pack(fill="x", pady=(8, 0))
        self.step_labels: list[ttk.Label] = []
        steps = [
            "录音识别与课程匹配",
            "SenseVoice 转录",
            "清洗转录文本",
            "考核分析",
            "归档到 Notion",
        ]
        for i, text in enumerate(steps, 1):
            lbl = ttk.Label(
                self.step_frame,
                text=f"{i}. {text}  — 等待",
                style="CardBody.TLabel",
                foreground="#6b7280",
            )
            lbl.pack(anchor="w", pady=2)
            self.step_labels.append(lbl)

        self.progress_bar = ttk.Progressbar(parent, mode="determinate", maximum=100)
        self.progress_bar.pack(fill="x", pady=(10, 0))
        self.progress_info = ttk.Label(parent, text="", style="CardBody.TLabel")
        self.progress_info.pack(anchor="w", pady=(4, 0))

    def _build_results_panel(self, parent):
        self.result_title = ttk.Label(parent, text="选择一项任务查看结果", style="CardTitle.TLabel")
        self.result_title.pack(anchor="w")

        self.result_body = ttk.Label(
            parent,
            text="处理完成后会显示课程信息、本地文件路径和 Notion 归档状态。",
            style="CardBody.TLabel",
            wraplength=700,
            justify="left",
        )
        self.result_body.pack(anchor="w", pady=(8, 0))

        self.result_actions = ttk.Frame(parent, style="Card.TFrame")
        self.result_actions.pack(fill="x", pady=(10, 0))

        self.open_txt_btn = tk.Button(
            self.result_actions,
            text="转录",
            state="disabled",
            bg="white",
            fg="#0d9488",
            relief="solid",
            cursor="hand2",
            command=lambda: self._open_path("output_path"),
        )
        self.open_txt_btn.pack(side="left", padx=(0, 6))

        self.open_cleaned_btn = tk.Button(
            self.result_actions,
            text="清洗稿",
            state="disabled",
            bg="white",
            fg="#8b5cf6",
            relief="solid",
            cursor="hand2",
            command=lambda: self._open_path("cleaned_path"),
        )
        self.open_cleaned_btn.pack(side="left", padx=(0, 6))

        self.open_summary_btn = tk.Button(
            self.result_actions,
            text="分析摘要",
            state="disabled",
            bg="white",
            fg="#6366f1",
            relief="solid",
            cursor="hand2",
            command=lambda: self._open_path("summary_path"),
        )
        self.open_summary_btn.pack(side="left", padx=(0, 6))

        self.notion_btn = tk.Button(
            self.result_actions,
            text="Notion",
            state="disabled",
            bg="#f3f4f6",
            fg="#9ca3af",
            relief="solid",
            cursor="hand2",
            command=self._open_notion,
        )
        self.notion_btn.pack(side="left")

        self.note_lbl = ttk.Label(
            parent,
            text="提示：结果文件分别保存在 txt/ 与 course-notes/outputs/；Notion 需要配置 .env 中的 NOTION_TOKEN。",
            style="CardBody.TLabel",
            foreground="#6b7280",
            wraplength=700,
        )
        self.note_lbl.pack(anchor="w", pady=(12, 0))

    # ----------------- 事件处理 -----------------

    def _on_start(self):
        if self.engine.running:
            messagebox.showinfo("提示", "处理已在运行中")
            return
        self.engine.start(monitor=self.monitor_var.get())
        self._set_running_ui(True)

    def _on_toggle_monitor(self):
        self.monitor_var.set(not self.monitor_var.get())
        if self.monitor_var.get():
            self.monitor_btn.config(text="持续监控：开", bg="#d1fae5", fg="#0f766e")
        else:
            self.monitor_btn.config(text="持续监控：关", bg="#e5e7eb", fg="#374151")

    def _on_stop(self):
        self.engine.stop()
        self._set_running_ui(False)

    def _set_running_ui(self, running: bool):
        if running:
            self.status_var.set("运行中")
            self.status_dot.config(fg="#10b981")
            self.start_btn.config(state="disabled", bg="#99f6e4")
        else:
            self.status_var.set("已停止")
            self.status_dot.config(fg="#6b7280")
            self.start_btn.config(state="normal", bg="#0d9488")

    def _start_polling(self):
        self._poll_events()

    def _poll_events(self):
        try:
            while True:
                event = self.event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self._polling_id = self.master.after(100, self._poll_events)

    def _handle_event(self, event: dict):
        kind = event.get("kind")
        if kind == "scan":
            self._refresh_stats()
            self._refresh_task_list()
        elif kind == "task_update":
            self._refresh_stats()
            self._refresh_task_list()
            self._update_progress(event.get("task_id"))
        elif kind == "progress":
            self._update_progress_bar(event.get("done", 0), event.get("total", 1))
        elif kind == "log":
            print(event.get("message"))
        elif kind == "state":
            self._set_running_ui(event.get("running", False))

    def _refresh_stats(self):
        stats = db.stats()
        self.pending_var.set(str(stats.get("pending", 0) + stats.get("waiting", 0)))
        self.done_var.set(str(stats.get("done_today", 0)))

    def _refresh_task_list(self):
        selected = self.tree.selection()
        selected_id = self.tree.item(selected[0])["values"][4] if selected else None

        for item in self.tree.get_children():
            self.tree.delete(item)

        filt = self.queue_filter.get()
        status_map = {
            "pending": [Status.PENDING, Status.WAITING],
            "processing": [Status.RENAME, Status.TRANSCRIBE, Status.CLEAN, Status.ANALYZE, Status.NOTION],
            "done": [Status.DONE],
            "failed": [Status.FAILED],
        }
        tasks = db.list_tasks()
        for task in tasks:
            if filt != "all" and task["status"] not in status_map.get(filt, []):
                continue
            label, _ = STATUS_STYLES.get(task["status"], (task["status"], "#6b7280"))
            filename = Path(task["current_path"]).name
            self.tree.insert(
                "",
                "end",
                values=(
                    filename,
                    task.get("course_name") or "—",
                    label,
                    task.get("record_date") or "—",
                    task["id"],
                ),
            )

        if selected_id is not None:
            for item in self.tree.get_children():
                if self.tree.item(item)["values"][4] == selected_id:
                    self.tree.selection_set(item)
                    break

    def _on_task_select(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        task_id = self.tree.item(selected[0])["values"][4]
        self._update_progress(task_id)

    def _update_progress(self, task_id: int | None):
        if task_id is None:
            return
        task = db.get_task_by_id(task_id)
        if not task:
            return

        course = task.get("course_name") or Path(task["current_path"]).name
        self.current_task_var.set(f"当前任务：{course}")

        status = task["status"]
        step_idx = -1
        if status == Status.RENAME:
            step_idx = 0
        elif status == Status.TRANSCRIBE:
            step_idx = 1
        elif status == Status.CLEAN:
            step_idx = 2
        elif status == Status.ANALYZE:
            step_idx = 3
        elif status == Status.NOTION:
            step_idx = 4
        elif status == Status.DONE:
            step_idx = 5
        elif status == Status.FAILED:
            step_idx = -1

        for i, lbl in enumerate(self.step_labels):
            base = lbl.cget("text").split("  — ")[0]
            if i < step_idx or status == Status.DONE:
                lbl.config(text=f"{base}  — 已完成", foreground="#10b981")
            elif i == step_idx:
                lbl.config(text=f"{base}  — 正在处理", foreground="#0d9488")
            else:
                lbl.config(text=f"{base}  — 等待", foreground="#6b7280")

        # 更新结果面板
        self._update_results(task)

    def _update_progress_bar(self, done: int, total: int):
        if total <= 0:
            return
        pct = int(done / total * 100)
        self.progress_bar["value"] = pct
        self.progress_info.config(text=f"转录进度：{done} / {total} 段（{pct}%）")

    def _update_results(self, task: dict):
        course = task.get("course_name") or "未识别课程"
        date = task.get("record_date") or "未识别日期"
        status_label, _ = STATUS_STYLES.get(task["status"], (task["status"], "#6b7280"))

        self.result_title.config(text=f"{course} · {date}")
        body = f"状态：{status_label}\n"
        if task.get("output_path"):
            body += f"转录：{task['output_path']}\n"
        if task.get("cleaned_path"):
            body += f"清洗稿：{task['cleaned_path']}\n"
        if task.get("summary_path"):
            body += f"摘要：{task['summary_path']}\n"
        if task.get("notion_page_id"):
            body += f"Notion 页面：{task['notion_page_id']}\n"
        if task.get("error"):
            body += f"错误：{task['error']}\n"
        self.result_body.config(text=body)

        self._selected_task = task
        for key, btn in [
            ("output_path", self.open_txt_btn),
            ("cleaned_path", self.open_cleaned_btn),
            ("summary_path", self.open_summary_btn),
        ]:
            if task.get(key) and Path(task[key]).exists():
                btn.config(state="normal")
            else:
                btn.config(state="disabled")

        if task.get("notion_page_id"):
            self.notion_btn.config(state="normal", fg="#ec4899", bg="white")
        else:
            self.notion_btn.config(state="disabled", fg="#9ca3af", bg="#f3f4f6")

    def _open_path(self, key: str):
        task = getattr(self, "_selected_task", None)
        if task and task.get(key):
            path = Path(task[key])
            if path.exists():
                os.startfile(str(path))

    def _open_notion(self):
        task = getattr(self, "_selected_task", None)
        if task and task.get("notion_page_id"):
            url = f"https://www.notion.so/{task['notion_page_id'].replace('-', '')}"
            os.startfile(url)

    def on_close(self):
        self.engine.stop()
        if self._polling_id:
            self.master.after_cancel(self._polling_id)
        self.master.destroy()
