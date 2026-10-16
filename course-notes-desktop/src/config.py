"""兼容层：旧代码 ``from .config import X`` 继续可用。

真正的唯一真源已经搬到项目根的 ``config/`` 包：
  * 路径        -> config/paths.py
  * 业务参数    -> config/settings.yaml + config/settings.py
本文件只做「转发」，不要再往这里加新配置。
"""
from __future__ import annotations

import sys
from pathlib import Path

# --- 把项目根加进 sys.path，使 config/ 与 core/ 可被 import ---
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import paths as _paths                 # noqa: E402
from config import settings as _settings           # noqa: E402

# --- 加载 .env（凭证）---
try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / "course-notes-desktop" / ".env")
except ImportError:
    pass

# ================= 路径（来自 config/paths.py）=================
BASE_DIR = _paths.BASE_DIR
SOUNDS_DIR = _paths.SOUNDS_DIR
TXT_DIR = _paths.TXT_DIR
OUTPUT_DIR = _paths.OUTPUTS_DESKTOP_DIR      # C-8：桌面临时输出到独立子目录，不再覆盖 Agent 的稿子
AGENT_OUTPUT_DIR = _paths.OUTPUTS_DIR        # 仅供对照/展示用
DATA_DIR = _paths.DB_PATH.parent
DB_PATH = _paths.DB_PATH
DB_SOURCE = _paths.DB_SOURCE          # "new" 或 "old(N rows)"，用于启动时提示
SCHEDULE_CANDIDATES = _paths.SCHEDULE_CANDIDATES
LOCK_FILE = _paths.LOCK_FILE

# ================= 提示词插件目录 =================
PLUGIN_DIR = _paths.PLUGIN_DIR
CLEANER_SKILL_MD = _paths.CLEANER_SKILL_MD
CLEANER_RULES_MD = _paths.CLEANER_RULES_MD
ANALYZER_SKILL_MD = _paths.ANALYZER_SKILL_MD
ANALYZER_SCHEMA_MD = _paths.ANALYZER_SCHEMA_MD

# ================= 业务参数（来自 config/settings.yaml）=================
SEMESTER_START = _settings.SEMESTER_START
MAX_GAP_MINUTES = _settings.MAX_GAP_MINUTES
SEGMENT_SEC = _settings.SEGMENT_SEC
SAMPLE_RATE = _settings.SAMPLE_RATE
SUFFIX = _settings.SUFFIX
AUDIO_EXTS = _settings.AUDIO_EXTS
MIN_FILE_SIZE = _settings.MIN_FILE_SIZE
STABLE_SECONDS = _settings.STABLE_SECONDS
POLL_INTERVAL_MS = int(_settings.POLL_INTERVAL * 1000)
MAX_ATTEMPTS = _settings.MAX_ATTEMPTS
RETRY_DELAY = _settings.RETRY_DELAY
RETRY_BACKOFF = _settings.RETRY_BACKOFF
PROCESS_EXISTING_ON_START = _settings.PROCESS_EXISTING_ON_START

# ================= LLM / Notion 凭证 =================
import os  # noqa: E402

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_ROOT_PAGE_ID = os.getenv("NOTION_ROOT_PAGE_ID", "")


# ================= 任务状态 =================
class Status:
    PENDING = "pending"          # 待处理
    WAITING = "waiting"          # 等待写入完成
    RENAME = "rename"            # 改名中
    TRANSCRIBE = "transcribe"    # 转录中
    CLEAN = "clean"              # 清洗中
    ANALYZE = "analyze"          # 考核分析中
    NOTION = "notion"            # Notion 归档中
    DONE = "done"                # 已完成
    FAILED = "failed"            # 失败


STEP_LABELS = {
    Status.WAITING: "等待文件稳定",
    Status.RENAME: "按课表改名",
    Status.TRANSCRIBE: "SenseVoice 转录",
    Status.CLEAN: "清洗转录文本",
    Status.ANALYZE: "考核分析",
    Status.NOTION: "归档到 Notion",
    Status.DONE: "完成",
    Status.FAILED: "失败",
}
