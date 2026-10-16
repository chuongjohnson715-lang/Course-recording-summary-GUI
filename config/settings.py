"""业务参数的 Python 视图。

读取同目录的 settings.yaml。若 yaml 库缺失或文件损坏，回落到安全默认值，
保证程序永远能启动（不会因为一个配置文件少个引号就整个起不来）。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

_SETTINGS_FILE = Path(__file__).resolve().parent / "settings.yaml"

# ------------------------- 默认值 -------------------------
_DEFAULTS = {
    "semester": {"start": "2026-08-31"},
    "schedule": {"max_gap_minutes": 45},
    "transcribe": {
        "segment_sec": 15,
        "sample_rate": 16000,
        "model": "iic/SenseVoiceSmall",
        "language": "zh",
        "use_itn": True,
        "suffix": "_sensevoice",
        "ffmpeg": "",
    },
    "watch": {
        "poll_interval_sec": 1.0,
        "stable_seconds": 3,
        "min_file_size": 1024,
        "process_existing_on_start": True,
    },
    "retry": {"max_attempts": 3, "delay_seconds": 5, "backoff": 2.0},
    "audio_exts": [".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma"],
}

_data = _DEFAULTS
_load_error: str | None = None

try:
    import yaml

    if _SETTINGS_FILE.exists():
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        # 浅层合并：缺失的键用默认值补齐
        merged = {k: dict(v) if isinstance(v, dict) else v for k, v in _DEFAULTS.items()}
        for key, val in loaded.items():
            if isinstance(val, dict) and isinstance(merged.get(key), dict):
                merged[key].update(val)
            else:
                merged[key] = val
        _data = merged
except Exception as exc:  # noqa: BLE001 - 启动健壮性优先
    _load_error = f"{type(exc).__name__}: {exc}"


# ------------------------- 学期与课表 -------------------------
def _parse_ymd(s: str) -> tuple[int, int, int]:
    y, m, d = (int(x) for x in str(s).split("-"))
    return y, m, d


SEMESTER_START: tuple[int, int, int] = _parse_ymd(
    _data["semester"].get("start", _DEFAULTS["semester"]["start"])
)
MAX_GAP_MINUTES: int = int(_data["schedule"].get("max_gap_minutes", 45))

# ------------------------- 转录参数 -------------------------
_t = _data["transcribe"]
SEGMENT_SEC: int = int(_t.get("segment_sec", 15))
SAMPLE_RATE: int = int(_t.get("sample_rate", 16000))
ASR_MODEL: str = str(_t.get("model", "iic/SenseVoiceSmall"))
ASR_LANGUAGE: str = str(_t.get("language", "zh"))
ASR_USE_ITN: bool = bool(_t.get("use_itn", True))
SUFFIX: str = str(_t.get("suffix", "_sensevoice"))
FFMPEG: str = str(_t.get("ffmpeg", "") or "")

# ------------------------- 监控参数 -------------------------
_w = _data["watch"]
POLL_INTERVAL: float = float(_w.get("poll_interval_sec", 1.0))
STABLE_SECONDS: int = int(_w.get("stable_seconds", 3))
MIN_FILE_SIZE: int = int(_w.get("min_file_size", 1024))
PROCESS_EXISTING_ON_START: bool = bool(_w.get("process_existing_on_start", True))

# ------------------------- 重试参数 -------------------------
_r = _data["retry"]
MAX_ATTEMPTS: int = int(_r.get("max_attempts", 3))
RETRY_DELAY: float = float(_r.get("delay_seconds", 5))
RETRY_BACKOFF: float = float(_r.get("backoff", 2.0))

# ------------------------- 音频后缀 -------------------------
AUDIO_EXTS: set[str] = {str(e).lower() for e in _data.get("audio_exts", _DEFAULTS["audio_exts"])}


def semester_start_date() -> date:
    return date(*SEMESTER_START)


# 供诊断用：settings.yaml 读取失败时的原因（None 表示正常）
load_error = _load_error


__all__ = [
    "SEMESTER_START",
    "MAX_GAP_MINUTES",
    "SEGMENT_SEC",
    "SAMPLE_RATE",
    "ASR_MODEL",
    "ASR_LANGUAGE",
    "ASR_USE_ITN",
    "SUFFIX",
    "FFMPEG",
    "POLL_INTERVAL",
    "STABLE_SECONDS",
    "MIN_FILE_SIZE",
    "PROCESS_EXISTING_ON_START",
    "MAX_ATTEMPTS",
    "RETRY_DELAY",
    "RETRY_BACKOFF",
    "AUDIO_EXTS",
    "semester_start_date",
    "load_error",
]
