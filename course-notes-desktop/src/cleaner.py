"""转录文本清洗（复用 transcript-cleaner Skill 的 prompt）。"""
import re
from pathlib import Path

from . import llm_client
from .config import (
    CLEANER_SKILL_MD,
    CLEANER_RULES_MD,
    OUTPUT_DIR,
)

# 转录稿里的时间戳形如 [00:12] 或 00:12:34
_TS_RE = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]|\b\d{1,2}:\d{2}:\d{2}\b")


def _has_front_matter(text: str) -> bool:
    """判断文本是否已以 YAML front matter 开头（首行 --- 且后面还有 --- 收尾）。"""
    lines = text.lstrip().splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return True
    return False


class TranscriptCleaner:
    """读取 TRAE 插件的清洗规则，调用 LLM 生成标准化清洗稿。"""

    def __init__(self):
        self.llm = llm_client.LLMClient()
        self.system_prompt = self._build_system_prompt()

    def is_configured(self) -> bool:
        return self.llm.is_configured()

    def _build_system_prompt(self) -> str:
        skill = llm_client.load_markdown(CLEANER_SKILL_MD)
        rules = llm_client.load_markdown(CLEANER_RULES_MD)
        return (
            "你是课堂录音转录清洗助手。请严格按以下 Skill 定义和清洗规则处理输入文本。\n\n"
            "===== SKILL =====\n"
            f"{skill}\n\n"
            "===== 清洗规则 =====\n"
            f"{rules}\n\n"
            "输出要求：\n"
            "1. 只输出清洗后的 Markdown 正文与末尾的清洗说明，不要输出额外解释。\n"
            "2. 必须保留时间戳锚点。\n"
            "3. 不要改写老师观点，不要删除判断信号词。"
        )

    def _make_prefix(
        self,
        course_name: str | None,
        record_date: str | None,
        source_name: str,
        has_timestamps: bool = False,
    ) -> str:
        cn = course_name or "未识别课程"
        rd = record_date or "未识别日期"
        # has_timestamps 不能再写死 true：SenseVoice 输出的是连续文本，
        # 本身不带时间戳，写 true 与正文用「段落序号锚点」的做法自相矛盾。
        ts_flag = "true" if has_timestamps else "false"
        return (
            f"---\n"
            f"source: {source_name}\n"
            f"asr_engine: SenseVoice\n"
            f"date: {rd}\n"
            f"course: {cn}\n"
            f"has_timestamps: {ts_flag}\n"
            f"low_confidence_segments: 0\n"
            f"---\n\n"
        )

    def clean(self, transcript_path: Path, course_name: str | None, record_date: str | None) -> Path:
        """清洗转录文件，返回 cleaned.md 路径。"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        raw_text = transcript_path.read_text(encoding="utf-8")
        user_prompt = (
            f"课程名：{course_name or '未识别'}\n"
            f"日期：{record_date or '未识别'}\n"
            f"原始文件名：{transcript_path.name}\n\n"
            "===== 原始转录 =====\n"
            f"{raw_text}\n\n"
            "请按系统提示中的规则清洗上述文本，输出 Markdown 格式。"
        )

        cleaned = self.llm.chat_completion(self.system_prompt, user_prompt)
        cleaned = cleaned.strip()

        # 判断原始转录里是否真的带时间戳，据此写 has_timestamps
        has_ts = bool(_TS_RE.search(raw_text))

        # 清洗 skill 自己也会按规则输出一段 YAML front matter。
        # 如果模型已经给了，就复用它（并保留模型对 has_timestamps 等字段的判断），
        # 避免出现两个互相矛盾的 front matter 块（例如程序写 true、模型写 false）。
        if _has_front_matter(cleaned):
            full_text = cleaned + "\n"
        else:
            full_text = (
                self._make_prefix(
                    course_name, record_date, transcript_path.name, has_timestamps=has_ts
                )
                + cleaned
                + "\n"
            )

        # 从文件名提取前缀：{课程名}-{日期}
        safe_course = re.sub(r'[<>:"/\\|?*]', "_", course_name or "未识别课程").strip()
        prefix_name = f"{safe_course}-{record_date or 'unknown'}"
        out_path = OUTPUT_DIR / f"{prefix_name}-cleaned.md"
        out_path.write_text(full_text, encoding="utf-8")
        return out_path
