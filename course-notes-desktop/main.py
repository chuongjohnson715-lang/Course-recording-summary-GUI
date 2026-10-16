#!/usr/bin/env python3
"""桌面程序入口。"""
import queue
import sys
import tkinter as tk
from pathlib import Path

# 把本项目目录加入路径，保证 src 可导入
ROOT = Path(__file__).resolve().parent
# 把仓库根目录（study/）也加入路径，保证 config/ 与 core/ 可导入。
# 不依赖 src.config 的导入顺序 —— 否则 core 的可用性会取决于 import 顺序。
REPO_ROOT = ROOT.parent
for _p in (str(ROOT), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src import db
from src.engine import ProcessingEngine
from src.ui import App


def main():
    db.init_db()

    root = tk.Tk()
    root.configure(bg="#f3f4f6")

    event_queue = queue.Queue()
    engine = ProcessingEngine(event_queue)

    app = App(root, engine)
    root.protocol("WM_DELETE_WINDOW", app.on_close)

    root.mainloop()


if __name__ == "__main__":
    main()
