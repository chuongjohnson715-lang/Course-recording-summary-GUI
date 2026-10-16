"""发布前隐私扫描：逐个检查被 git 跟踪的文件是否含个人/敏感内容。

用法：
    .venv\\Scripts\\python.exe tools\\privacy_scan.py

设计原则：只读，不修改任何文件。退出码非 0 表示发现疑似问题。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 通用高危模式：不写死任何个人真实信息，因此本文件本身可以安全公开。
#
# 如果你想把「真名 / 学校 / 公司 / 地名」等个性化词也纳入检查，
# 建一个私有词表（默认 .privacy_words.txt，已被 .gitignore 排除），
# 每行一个词，本脚本会自动读取。
PATTERNS: list[tuple[str, str]] = [
    ("手机号", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("身份证号", r"(?<!\d)\d{17}[\dXx](?!\d)"),
    ("邮箱", r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    ("LLM密钥", r"sk-[A-Za-z0-9_-]{16,}"),
    ("Notion令牌", r"(ntn_|secret_)[A-Za-z0-9]{20,}"),
    ("GitHub令牌", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("云厂商Key", r"AKIA[0-9A-Z]{16}"),
    ("私钥块", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("本机用户路径", r"[A-Za-z]:\\Users\\[^\\\s\"']+|/Users/[^/\s\"']+/"),
    ("内网/本机地址", r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d+\.\d+\b"),
]

# 允许出现的例外（占位符、刻意的示例文字、正当的功能代码）
ALLOWLIST = [
    "sk-在这里粘贴你的DeepSeek密钥",
    "sk-xxxxxxxx",
    "sk-xxxx",
    "your_api_key",
    # README / 代码注释里作为「不要写死用户名」反例出现的通用示例
    "C:\\Users\\<user>",
    "C:\\Users\\<用户名>",
    "C:\\Users\\...",
    # TRAE 插件目录约定（与具体用户名无关的正当功能代码）
    ".trae-cn",
]

# 私有词表：每行一个自定义敏感词（真名、学校、公司、地名……）。
# 该文件已被 .gitignore 排除，不会随仓库公开。
WORDS_FILE = ROOT / ".privacy_words.txt"


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def load_custom_words() -> list[str]:
    """读取私有词表；不存在则返回空列表。"""
    if not WORDS_FILE.exists():
        return []
    words: list[str] = []
    for line in WORDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(line)
    return words


def main() -> int:
    files = tracked_files()
    custom = load_custom_words()

    print(f"被 git 跟踪的文件：{len(files)} 个")
    if custom:
        print(f"私有词表：{WORDS_FILE.name}（{len(custom)} 个自定义词）")
    else:
        print(f"私有词表：无（可选，建 {WORDS_FILE.name} 可检查真名/学校等个性化词）")
    print("=" * 62)

    patterns = list(PATTERNS)
    if custom:
        patterns.append(("私有词表", "|".join(re.escape(w) for w in custom)))

    findings: list[tuple[str, str, int, str]] = []

    for rel in files:
        path = ROOT / rel
        if not path.is_file():
            continue
        # 跳过本脚本自身：它必须包含"示例密钥/占位符"这类字面量
        if path.resolve() == Path(__file__).resolve():
            continue
        # 二进制文件跳过内容扫描（音频/图片等）
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for label, pattern in patterns:
            for m in re.finditer(pattern, text):
                snippet = m.group(0)
                line_no = text[: m.start()].count("\n") + 1
                if any(a in snippet for a in ALLOWLIST):
                    continue
                findings.append((rel, label, line_no, snippet))

    if findings:
        print("发现疑似敏感内容：\n")
        for rel, label, line_no, snippet in findings:
            print(f"  [{label}] {rel}:{line_no}  ->  {snippet!r}")
        print()
        print(f"合计 {len(findings)} 处，请人工确认后决定是否发布。")
        return 1

    print("未发现敏感内容。")
    print("（已扫描手机号/身份证/邮箱/各类密钥/私钥/本机用户路径/内网地址）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
