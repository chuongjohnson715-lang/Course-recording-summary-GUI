"""通用 LLM 客户端（OpenAI 兼容接口）。"""
from pathlib import Path

from .config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class LLMClient:
    """基于 OpenAI SDK 的通用调用封装。"""

    def __init__(self):
        if OpenAI is None:
            raise RuntimeError(
                "缺少 openai 包。请运行：pip install -r requirements.txt"
            )
        self.client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        self.model = OPENAI_MODEL

    def is_configured(self) -> bool:
        return bool(OPENAI_API_KEY)

    def chat_completion(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """同步调用 LLM，返回文本内容。"""
        if not self.is_configured():
            raise RuntimeError("LLM 未配置：请在 .env 中设置 OPENAI_API_KEY")

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""


def load_markdown(path: Path) -> str:
    """读取 markdown 文件内容；不存在则返回空字符串。"""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
