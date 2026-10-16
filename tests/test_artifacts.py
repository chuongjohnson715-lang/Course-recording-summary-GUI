"""清洗/分析产物的格式回归测试（不需要 API Key）。

覆盖端到端跑真实链路时发现的两个缺陷：
  1. 清洗稿出现两个 YAML front matter 块，且 has_timestamps 自相矛盾
     （程序写 true，模型写 false）——因为程序无条件再拼一份前缀。
  2. 摘要文件名是 ...-analysis.md，而 engine/手册期望 ...-summary.md
     （analyzer 用 with_suffix('.md') 把 ...-analysis.json 的 .json 换掉）。

用假的 LLM 客户端驱动真实的 cleaner/analyzer 代码，因此不联网。

运行：
    python tests/test_artifacts.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "course-notes-desktop"

_SANDBOX = Path(tempfile.mkdtemp(prefix="cn_artifacts_"))
os.environ["COURSE_NOTES_BASE_DIR"] = str(_SANDBOX)

for p in (str(DESKTOP), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


# --- 模拟模型返回：带 front matter 的清洗稿 / 合规 JSON ---
CLEANED_WITH_FM = """---
source: x_sensevoice.txt
asr_engine: SenseVoice
date: 2026-10-12
course: 算法设计与分析
has_timestamps: false
low_confidence_segments: 0
---

## [段落-01] 正文标题

**段落-01** 这是清洗后的正文内容。
"""

ANALYSIS_JSON = json.dumps(
    {
        "course_info": {"course_name": "算法设计与分析", "date": "2026-10-12"},
        "assessment": {
            "final_exam": {
                "explicit_exam_points": [
                    {"topic": "动态规划", "evidence": {"timestamp": "段落-01"}}
                ],
                "possible_exam_points": [],
            }
        },
        "quizzes": [{"content": "小测", "deadline": "下周三"}],
        "assignments": [],
        "teacher_emphasis": [],
        "knowledge_points": [
            {"topic": "DP", "importance": "高", "summary": "核心思想"}
        ],
        "course_notices": "无",
        "pending_confirmations": "无",
    },
    ensure_ascii=False,
)


def count_front_matter_blocks(text: str) -> int:
    """统计文本开头连续的 front matter 块数量。"""
    lines = text.lstrip("\ufeff").splitlines()
    blocks = 0
    i = 0
    while i < len(lines):
        if lines[i].strip() != "---":
            break
        # 找到配对的收尾 ---
        j = i + 1
        while j < len(lines) and lines[j].strip() != "---":
            j += 1
        if j >= len(lines):
            break
        blocks += 1
        i = j + 1
        # 跳过空行，看是否紧跟着又一个 ---
        while i < len(lines) and not lines[i].strip():
            i += 1
    return blocks


def main() -> int:
    import shutil

    from src import llm_client
    from src.analyzer import CourseAnalyzer
    from src.cleaner import TranscriptCleaner

    # --- 替换 LLM 调用，避免联网 ---
    calls = {"clean": 0, "analyze": 0}

    def fake_chat(self, system_prompt, user_prompt, temperature=0.2):
        # 用两个 prompt 里各自独有的标识来区分，不能用「清洗」——
        # 分析器的系统提示里也含「清洗稿」字样。
        if "转录清洗助手" in system_prompt:
            calls["clean"] += 1
            return CLEANED_WITH_FM
        calls["analyze"] += 1
        return ANALYSIS_JSON

    llm_client.LLMClient.chat_completion = fake_chat
    llm_client.LLMClient.is_configured = lambda self: True

    # 造一个不含时间戳的转录稿
    transcript = _SANDBOX / "txt" / "x_sensevoice.txt"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "audio: x.m4a\nmodel: SenseVoiceSmall\n" + "=" * 60 + "\n\n好，同学们，我们开始上课。\n",
        encoding="utf-8",
    )

    print("=== 1. 清洗稿只能有一个 front matter 块 ===")
    cleaner = TranscriptCleaner()
    cleaned = cleaner.clean(transcript, "算法设计与分析", "2026-10-12")
    text = cleaned.read_text(encoding="utf-8")
    blocks = count_front_matter_blocks(text)
    check("front matter 块数 == 1", blocks == 1, f"-> 实际 {blocks}")
    check("模型已给 front matter 时不再重复拼接",
          text.count("source:") == 1, f"-> source 出现 {text.count('source:')} 次")

    print("=== 2. has_timestamps 必须与转录稿实际情况一致 ===")
    check("无时间戳的转录 -> has_timestamps: false",
          "has_timestamps: false" in text, f"-> {[l for l in text.splitlines() if 'has_timestamps' in l]}")

    # 再验一个带时间戳的转录稿
    ts_transcript = _SANDBOX / "txt" / "y_sensevoice.txt"
    ts_transcript.write_text(
        "audio: y.m4a\n[00:12] 好，我们开始上课。\n", encoding="utf-8"
    )
    # 让模型这次不返回 front matter，走程序生成分支
    original = llm_client.LLMClient.chat_completion

    def no_fm_chat(self, system_prompt, user_prompt, temperature=0.2):
        if "转录清洗助手" in system_prompt:
            return "## [00:12] 正文\n\n好，我们开始上课。\n"
        return ANALYSIS_JSON

    llm_client.LLMClient.chat_completion = no_fm_chat
    cleaned2 = cleaner.clean(ts_transcript, "算法设计与分析", "2026-10-12")
    text2 = cleaned2.read_text(encoding="utf-8")
    check("程序生成前缀时块数为 1", count_front_matter_blocks(text2) == 1,
          f"-> {count_front_matter_blocks(text2)}")
    check("带时间戳的转录 -> has_timestamps: true",
          "has_timestamps: true" in text2,
          f"-> {[l for l in text2.splitlines() if 'has_timestamps' in l]}")
    llm_client.LLMClient.chat_completion = original

    print("=== 3. 摘要文件名必须是 -summary.md ===")
    analyzer = CourseAnalyzer()
    analysis_path, summary_path = analyzer.analyze(cleaned, "算法设计与分析", "2026-10-12")
    check("analysis.json 文件名正确", analysis_path.name == "算法设计与分析-2026-10-12-analysis.json",
          f"-> {analysis_path.name}")
    check("summary.md 文件名正确（不是 -analysis.md）",
          summary_path.name == "算法设计与分析-2026-10-12-summary.md",
          f"-> {summary_path.name}")
    check("两个文件都存在", analysis_path.exists() and summary_path.exists())
    check("JSON 与摘要不是同一个文件", analysis_path != summary_path)

    print("=== 4. 摘要内容可读且引用了解析结果 ===")
    summary_text = summary_path.read_text(encoding="utf-8")
    check("摘要含标题", "# 课程分析摘要" in summary_text, f"-> {summary_text[:60]!r}")
    check("摘要含考试重点", "考试重点" in summary_text)
    check("摘要含知识点", "动态规划" in summary_text or "DP" in summary_text)

    print("=== 5. 产物落在 outputs/desktop 下 ===")
    from src.config import OUTPUT_DIR
    check("清洗稿在 desktop 子目录", OUTPUT_DIR in cleaned.parents, f"-> {cleaned}")
    check("摘要在 desktop 子目录", OUTPUT_DIR in summary_path.parents, f"-> {summary_path}")

    shutil.rmtree(_SANDBOX, ignore_errors=True)
    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[PASSED] 清洗/分析产物格式回归通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
