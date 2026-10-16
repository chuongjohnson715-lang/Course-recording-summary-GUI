"""课程考核分析（复用 course-assessment-analyzer Skill 的 prompt）。"""
import json
import re
from pathlib import Path

from . import llm_client
from .config import ANALYZER_SKILL_MD, ANALYZER_SCHEMA_MD, OUTPUT_DIR


class CourseAnalyzer:
    """读取 TRAE 插件的考核分析规则，调用 LLM 生成 V1.1 JSON 与摘要。"""

    def __init__(self):
        self.llm = llm_client.LLMClient()
        self.system_prompt = self._build_system_prompt()

    def is_configured(self) -> bool:
        return self.llm.is_configured()

    def _build_system_prompt(self) -> str:
        skill = llm_client.load_markdown(ANALYZER_SKILL_MD)
        schema = llm_client.load_markdown(ANALYZER_SCHEMA_MD)
        return (
            "你是课程重点与考核分析助手。请严格按以下 Skill 和 Schema 分析输入的清洗稿。\n\n"
            "===== SKILL =====\n"
            f"{skill}\n\n"
            "===== SCHEMA =====\n"
            f"{schema}\n\n"
            "输出要求：\n"
            "1. 只输出纯 JSON，不要 Markdown 代码块，不要额外解释。\n"
            "2. 必须严格遵循 V1.1 Schema 的字段结构与空值约定。\n"
            "3. 每条重要信息必须有 evidence（时间戳 + 原话）。"
        )

    def _write_summary(self, data: dict, out_path: Path) -> Path:
        lines = ["# 课程分析摘要", ""]

        pending = data.get("pending_confirmations", "无")
        if pending != "无" and pending:
            lines.extend(["## ⚠️ 待确认事项", ""])
            for item in pending:
                lines.append(f"- **{item.get('content', '')}** ({item.get('evidence', {}).get('timestamp', '')})")
            lines.append("")

        quizzes = data.get("quizzes", "无")
        assignments = data.get("assignments", "无")
        lines.extend(["## 📌 作业与小测", ""])
        if quizzes != "无" and quizzes:
            for q in quizzes:
                lines.append(f"- {q.get('content', '')} · 截止：{q.get('deadline', '未说明')}")
        if assignments != "无" and assignments:
            for a in assignments:
                lines.append(f"- {a.get('content', '')} · 截止：{a.get('deadline', '未说明')} · 提交：{a.get('submission', '未说明')}")
        if (quizzes == "无" or not quizzes) and (assignments == "无" or not assignments):
            lines.append("- 无")
        lines.append("")

        lines.extend(["## 🎯 考试重点", ""])
        assessment = data.get("assessment", "无")
        if isinstance(assessment, dict):
            final = assessment.get("final_exam", {})
            explicit = final.get("explicit_exam_points", [])
            possible = final.get("possible_exam_points", [])
            if explicit:
                lines.append("### 明确考点")
                for item in explicit:
                    lines.append(f"- {item.get('topic', '')} ({item.get('evidence', {}).get('timestamp', '')})")
                lines.append("")
            if possible:
                lines.append("### 可能考点")
                for item in possible:
                    lines.append(f"- {item.get('topic', '')} ({item.get('evidence', {}).get('timestamp', '')})")
                lines.append("")
            if not explicit and not possible:
                lines.append("- 无明确考试信息\n")
        else:
            lines.append("- 无\n")

        emphasis = data.get("teacher_emphasis", "无")
        lines.extend(["## 💡 老师强调", ""])
        if emphasis != "无" and emphasis:
            for item in emphasis:
                lines.append(f"- {item.get('topic', '')} ({item.get('evidence', {}).get('timestamp', '')})")
        else:
            lines.append("- 无")
        lines.append("")

        notices = data.get("course_notices", "无")
        lines.extend(["## 📢 课程通知", ""])
        if notices != "无" and notices:
            for item in notices:
                lines.append(f"- {item.get('content', '')}")
        else:
            lines.append("- 无")
        lines.append("")

        kps = data.get("knowledge_points", "无")
        lines.extend(["## 📚 本节知识点", ""])
        if kps != "无" and kps:
            for kp in kps:
                lines.append(f"- **{kp.get('topic', '')}**（重要性：{kp.get('importance', '中')}）：{kp.get('summary', '')}")
        else:
            lines.append("- 无")
        lines.append("")

        # 摘要文件名固定为 {课程名}-{日期}-summary.md
        # 注意：不能用 out_path.with_suffix(".md") —— out_path 是 "...-analysis.json"，
        # with_suffix 只会把 ".json" 换成 ".md"，得到 "...-analysis.md"，
        # 与 engine/手册期望的 "-summary.md" 不一致。
        summary_path = out_path.parent / (out_path.stem[: -len("-analysis")] + "-summary.md")
        summary_path.write_text("\n".join(lines), encoding="utf-8")
        return summary_path

    def analyze(self, cleaned_path: Path, course_name: str | None, record_date: str | None) -> tuple[Path, Path]:
        """分析清洗稿，返回 (analysis.json, summary.md) 路径。"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        cleaned_text = cleaned_path.read_text(encoding="utf-8")
        user_prompt = (
            f"课程名：{course_name or '未识别'}\n"
            f"日期：{record_date or '未识别'}\n\n"
            "===== 清洗稿 =====\n"
            f"{cleaned_text}\n\n"
            "请按系统提示中的 V1.1 Schema 分析上述清洗稿，输出严格符合 Schema 的 JSON。"
        )

        raw = self.llm.chat_completion(self.system_prompt, user_prompt, temperature=0.1)
        # 去除可能的 markdown 代码块
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)

        # 写入 JSON
        safe_course = re.sub(r'[<>:"/\\|?*]', "_", course_name or "未识别课程").strip()
        prefix_name = f"{safe_course}-{record_date or 'unknown'}"
        analysis_path = OUTPUT_DIR / f"{prefix_name}-analysis.json"
        analysis_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 生成摘要
        summary_path = self._write_summary(data, analysis_path)
        return analysis_path, summary_path
