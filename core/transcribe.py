"""SenseVoice 转录（C-5 的唯一实现）。

历史背景：本逻辑曾在三处各写一遍 ——
  * sensevoice/watch_and_transcribe.py（transcribe_long_audio）
  * sensevoice/transcribe_sounds.py（整份拷贝，还写死了单个音频文件名）
  * course-notes-desktop/src/transcriber.py（Transcriber 类）
三处各自重复 SEGMENT_SEC=15 / SAMPLE_RATE=16000 常量。

合并要点
--------
1. 参数统一来自 config/settings.yaml。
2. ffmpeg 失败不再静默产出空音频（C-10）：检查 returncode 并校验解码结果，
   失败时抛带 ffmpeg stderr 的异常，让上层把任务标成 failed 而不是写出空稿。
3. 同时提供类接口（桌面用，带取消/进度）和函数接口（命令行用）。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

try:  # 正常情况：项目根已在 sys.path 上
    from core.schedule import TAG_PATTERN
    from config import settings
except ImportError:  # 允许被单独以文件路径方式 import
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.schedule import TAG_PATTERN
    from config import settings


class FFmpegError(RuntimeError):
    """ffmpeg 不可用或解码失败。"""


def resolve_ffmpeg() -> str:
    """定位 ffmpeg：settings.yaml 指定 > PATH 查找。"""
    configured = settings.FFMPEG.strip()
    if configured:
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FFmpegError(
        "找不到 ffmpeg。请安装 ffmpeg 并加入 PATH（或把完整路径填进 "
        "config/settings.yaml 的 transcribe.ffmpeg）。"
    )


def load_audio(path: Path, sr: int | None = None):
    """用 ffmpeg 把音频解码成单声道 float32 numpy 数组。

    与旧实现的区别：检查 returncode，失败直接抛错，绝不返回空数组。
    """
    sr = sr or settings.SAMPLE_RATE
    ffmpeg = resolve_ffmpeg()
    cmd = [
        ffmpeg, "-i", str(path),
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", str(sr),
        "-loglevel", "error", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True)
    except FileNotFoundError as exc:
        raise FFmpegError(f"ffmpeg 无法启动: {ffmpeg}") from exc

    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise FFmpegError(
            f"ffmpeg 解码失败（returncode={result.returncode}）: {path.name}\n{detail[:500]}"
        )

    if not result.stdout:
        raise FFmpegError(f"ffmpeg 未产出任何音频数据（文件可能损坏或不是音频）: {path.name}")

    audio = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sr


def clean_text(text: str) -> str:
    """去除 SenseVoice 输出的语言/情感等特殊标记。"""
    return TAG_PATTERN.sub("", text).strip()


def default_model():
    """懒加载 SenseVoice 模型（避免启动阶段就依赖 torch）。"""
    from funasr import AutoModel

    return AutoModel(model=settings.ASR_MODEL)


def transcribe_segment(audio_segment, model) -> str:
    res = model.generate(
        input=audio_segment,
        language=settings.ASR_LANGUAGE,
        use_itn=settings.ASR_USE_ITN,
        batch_size_s=10,
    )
    return clean_text(res[0]["text"])


def transcribe_long_audio(audio_path: Path, model, on_progress=None, verbose: bool = False) -> str:
    """按 SEGMENT_SEC 切段逐段识别，拼接成完整文本。"""
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log(f"  加载音频: {audio_path.name} ...")
    y, sr = load_audio(audio_path)
    total_samples = len(y)
    segment_samples = settings.SEGMENT_SEC * settings.SAMPLE_RATE
    total_segments = int(np.ceil(total_samples / segment_samples)) if total_samples else 0
    log(f"  时长: {total_samples / settings.SAMPLE_RATE:.1f}s，"
        f"切分为 {total_segments} 段（每段 {settings.SEGMENT_SEC}s）")

    texts: list[str] = []
    for i in range(total_segments):
        start = i * segment_samples
        end = min(start + segment_samples, total_samples)
        texts.append(transcribe_segment(y[start:end], model))
        if on_progress:
            on_progress(i + 1, total_segments)
        log(f"  段 {i + 1}/{total_segments} 完成")

    return "".join(texts)


def transcript_path_for(audio_path: Path, out_dir: Path | None = None) -> Path:
    from config import paths

    out_dir = out_dir or paths.TXT_DIR
    return out_dir / f"{audio_path.stem}{settings.SUFFIX}.txt"


def write_transcript(audio_path: Path, text: str, out_dir: Path | None = None) -> Path:
    """写出转录文本，返回输出路径。"""
    out_path = transcript_path_for(audio_path, out_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"audio: {audio_path.name}\n")
        f.write(
            f"model: {settings.ASR_MODEL} (language={settings.ASR_LANGUAGE}, "
            f"use_itn={settings.ASR_USE_ITN}, segment={settings.SEGMENT_SEC}s)\n"
        )
        f.write("=" * 60 + "\n\n")
        f.write(text + "\n")
    return out_path


def transcribe_file(audio_path: Path, model=None, on_progress=None, verbose: bool = False) -> Path:
    """命令行入口用：转录单个文件并写出 txt，返回输出路径。"""
    if model is None:
        log = print if verbose else (lambda *_: None)
        log("  首次触发，正在加载 SenseVoice 模型...")
        model = default_model()
        log("  模型加载完成。")
    text = transcribe_long_audio(audio_path, model, on_progress=on_progress, verbose=verbose)
    return write_transcript(audio_path, text)


class Transcriber:
    """桌面程序用：带懒加载与取消能力的转录器。"""

    def __init__(self) -> None:
        self._model = None
        self._cancelled = False

    def load(self):
        if self._model is None:
            self._model = default_model()

    def cancel(self) -> None:
        self._cancelled = True

    def reset_cancel(self) -> None:
        self._cancelled = False

    @property
    def ready(self) -> bool:
        return self._model is not None

    def transcribe(self, audio_path: Path, on_progress=None) -> Path:
        """转录音频文件，返回输出 txt 路径。"""
        self.load()
        self._cancelled = False

        y, sr = load_audio(audio_path)
        total_samples = len(y)
        segment_samples = settings.SEGMENT_SEC * settings.SAMPLE_RATE
        total_segments = int(np.ceil(total_samples / segment_samples)) if total_samples else 0

        texts: list[str] = []
        for i in range(total_segments):
            if self._cancelled:
                raise InterruptedError("转录已取消")
            start = i * segment_samples
            end = min(start + segment_samples, total_samples)
            texts.append(transcribe_segment(y[start:end], self._model))
            if on_progress:
                on_progress(i + 1, total_segments)

        return write_transcript(audio_path, "".join(texts))
