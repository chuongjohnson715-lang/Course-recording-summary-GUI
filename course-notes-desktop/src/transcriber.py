"""兼容层：转录逻辑已合并到 core/transcribe.py（C-5）。

保留 ``Transcriber`` 类名与 ``transcribe()`` 签名，内部转发到 core，
让 engine.py / ui.py 完全不用改。新代码请直接 ``from core import transcribe``。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.transcribe import (                     # noqa: E402,F401
    FFmpegError,
    Transcriber,
    clean_text,
    default_model,
    load_audio,
    resolve_ffmpeg,
    transcribe_long_audio,
    transcribe_segment,
    write_transcript,
)
