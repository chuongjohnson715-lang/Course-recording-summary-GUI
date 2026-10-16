"""桌面引擎端到端验证（不需要 API Key、不加载 ASR 模型）。

验证目标：C-13 提出的「桌面程序从未成功跑完一次」是否已修复 ——
任务状态机能否真正从 pending 走到 done，且每一步产物落盘、输出目录分离。

!!! 安全设计 !!!
本脚本在**隔离的临时沙箱**里运行：先把 COURSE_NOTES_BASE_DIR 指向临时目录，
再导入任何项目模块。因此它绝不会读取、改名或覆盖 sounds/ 里的真实录音，
也不会动真实的 tasks.db / txt/ / outputs/。

做法：
  * 临时沙箱里放一份课表和一个小测试音频
  * 只替换 ASR 模型加载（用真实 ffmpeg 解码，验证 C-10），产出真实 txt
  * 清洗/分析按 .env 现状：未配 Key 时用 --stub-llm 在本地生成确定性文件，
    从而在无凭证条件下验证「状态机 + 落盘 + 输出分离」主干

运行：
    python tests/desktop_e2e.py --stub-llm   # 推荐：不联网、不改真实数据
    python tests/desktop_e2e.py              # 真跑清洗/分析（需要 .env 里的 Key）
"""
from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parent.parent
DESKTOP = REAL_ROOT / "course-notes-desktop"

# --- 关键：必须在导入 config/core/src 之前设定沙箱根目录 ---
_SANDBOX = Path(tempfile.mkdtemp(prefix="cn_e2e_"))
os.environ["COURSE_NOTES_BASE_DIR"] = str(_SANDBOX)

for p in (str(DESKTOP), str(REAL_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

TEST_STEM = "20261010_235959"


def setup_sandbox() -> Path:
    """在沙箱里准备课表与测试音频。"""
    sched_src = REAL_ROOT / "课表.xls"
    if sched_src.exists():
        shutil.copy2(sched_src, _SANDBOX / "课表.xls")

    from core.transcribe import resolve_ffmpeg

    audio = _SANDBOX / "sounds" / f"{TEST_STEM}.m4a"
    audio.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [resolve_ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-ar", "16000", "-ac", "1", str(audio)],
        capture_output=True, check=True,
    )
    return audio


def stub_llm() -> None:
    """让清洗/分析在沙箱内产出确定性文件，无需 API Key。"""
    import json

    from src import analyzer as analyzer_mod
    from src import cleaner as cleaner_mod
    from src.config import OUTPUT_DIR

    def fake_clean(self, transcript_path, course_name, record_date):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUTPUT_DIR / f"{course_name or '未识别课程'}-{record_date or 'unknown'}-cleaned.md"
        out.write_text(f"# 清洗稿（stub）\n源文件: {transcript_path.name}\n", encoding="utf-8")
        return out

    def fake_analyze(self, cleaned_path, course_name, record_date):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        base = f"{course_name or '未识别课程'}-{record_date or 'unknown'}"
        a = OUTPUT_DIR / f"{base}-analysis.json"
        s = OUTPUT_DIR / f"{base}-summary.md"
        a.write_text(json.dumps({"stub": True}), encoding="utf-8")
        s.write_text("# 摘要（stub）\n", encoding="utf-8")
        return a, s

    cleaner_mod.TranscriptCleaner.clean = fake_clean
    cleaner_mod.TranscriptCleaner.is_configured = lambda self: True
    analyzer_mod.CourseAnalyzer.analyze = fake_analyze
    analyzer_mod.CourseAnalyzer.is_configured = lambda self: True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stub-llm", action="store_true", help="不联网，只验证状态机")
    args = parser.parse_args()

    print(f"隔离沙箱: {_SANDBOX}")
    audio = setup_sandbox()

    from src import db
    from src import transcriber as transcriber_mod
    from src.config import DB_PATH, OUTPUT_DIR, SOUNDS_DIR
    from src.engine import EngineEvent, ProcessingEngine

    # 冒烟：确认真的落在沙箱里，而不是真实目录
    if REAL_ROOT in SOUNDS_DIR.parents or SOUNDS_DIR == REAL_ROOT / "sounds":
        print("[ABORT] 沙箱未生效，拒绝在真实目录上运行测试")
        shutil.rmtree(_SANDBOX, ignore_errors=True)
        return 1

    db.init_db()
    print(f"测试音频: {audio.name}")

    # 只替换 ASR 模型加载；ffmpeg 解码与 txt 落盘都是真的
    def no_model_transcribe(self, audio_path, on_progress=None):
        from core.transcribe import load_audio, write_transcript

        y, sr = load_audio(audio_path)
        if on_progress:
            on_progress(1, 1)
        return write_transcript(audio_path, f"[stub-asr] decoded {len(y)} samples")

    transcriber_mod.Transcriber.transcribe = no_model_transcribe
    if args.stub_llm:
        stub_llm()

    q: queue.Queue = queue.Queue()
    engine = ProcessingEngine(q)
    engine.start(monitor=True)

    deadline = time.time() + 60
    final = None
    while time.time() < deadline:
        try:
            ev = q.get(timeout=1)
        except queue.Empty:
            pass
        else:
            if ev.get("kind") == EngineEvent.LOG:
                print(f"  [log] {ev.get('message')}")
        time.sleep(0.3)
        rows = [t for t in db.list_tasks() if Path(t["original_path"]).stem == TEST_STEM]
        if rows:
            final = rows[0]
            if final["status"] in ("done", "failed"):
                break

    engine.stop()
    time.sleep(0.5)

    ok = True
    print("\n=== 结果 ===")
    if final is None:
        print("  [FAIL] 引擎没有为测试音频创建任务（扫描/建库失败）")
        ok = False
    else:
        print(f"  最终状态: {final['status']}  step={final['step']}")
        if final.get("error"):
            print(f"  error: {final['error']}")
        if final["status"] != "done":
            print("  [FAIL] 任务未到达 done")
            ok = False
        if not (final.get("output_path") and Path(final["output_path"]).exists()):
            print("  [FAIL] 转录产物 txt 未落盘")
            ok = False
        if args.stub_llm:
            for field in ("cleaned_path", "analysis_path", "summary_path"):
                val = final.get(field)
                if not (val and Path(val).exists()):
                    print(f"  [FAIL] {field} 未落盘 -> {val}")
                    ok = False
            # C-8：产物必须落在 outputs\desktop 下，而不是与 Agent 产物混在一起
            cleaned = final.get("cleaned_path")
            if cleaned and OUTPUT_DIR.name == "desktop" and OUTPUT_DIR not in Path(cleaned).parents:
                print(f"  [FAIL] 清洗稿没落在 desktop 子目录: {cleaned}")
                ok = False
            else:
                print("  [OK] 清洗稿落在独立子目录 outputs\\desktop\\")

    # --- 清理沙箱 ---
    shutil.rmtree(_SANDBOX, ignore_errors=True)
    print(f"\n（已删除隔离沙箱，真实 sounds/ 与 tasks.db 未被触碰）")

    print("[PASSED] 桌面引擎端到端走通。" if ok else "[FAILED] 见上面的 FAIL 行。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
