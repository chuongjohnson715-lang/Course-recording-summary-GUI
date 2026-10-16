"""自检：确认硬编码路径扫描**不是空断言**。

背景：tests/smoke_test.py 里那条「全仓 .py 无硬编码 C:\\Users 代码行」的检查，
原实现只看一个文件、且把以 # 开头的行排除，而唯一命中恰好是文件头注释里的说明文字，
所以它无论代码怎么写都会通过（vacuous，独立复核时被指出）。

本脚本用一个「故意违规」的沙箱证明修好后的扫描**能真的抓到违规**：
  - 沙箱里放一个含硬编码代码行的 .py -> 必须被抓到
  - 沙箱里放一个只在注释里提到该路径的 .py -> 必须不算违规

运行：
    python tests/test_path_guard.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_PARTS = (".venv", "\\venv\\", "__pycache__", "\\legacy\\", "\\archive\\", "\\.git\\", "\\.tmp\\")
NEEDLE = "C:" + "\\" + "Users" + "\\"      # 拼出来，避免本文件自己被判违规


def scan_roots(roots: list[Path]) -> tuple[list[str], list[str]]:
    """返回 (代码行命中, 注释/文档命中)。与 smoke_test.py 中的判据保持一致。"""
    code_hits: list[str] = []
    doc_hits: list[str] = []
    for root in roots:
        for py in root.rglob("*.py"):
            sp = str(py)
            if any(part in sp for part in SKIP_PARTS):
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if NEEDLE not in line:
                    continue
                s = line.strip()
                if s.startswith("#") or s.startswith('"') or s.startswith("'"):
                    doc_hits.append(f"{py.name}:{i}")
                else:
                    code_hits.append(f"{py.name}:{i}")
    return code_hits, doc_hits


failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="cn_pathguard_"))
    try:
        bad_dir = sandbox / "badpkg"
        bad_dir.mkdir(parents=True)
        (bad_dir / "violates.py").write_text(
            'BASE_DIR = Path(r"' + NEEDLE + 'someuser\\Desktop\\study")\n', encoding="utf-8"
        )

        comment_dir = sandbox / "commentpkg"
        comment_dir.mkdir(parents=True)
        (comment_dir / "mentions.py").write_text(
            "# 说明：不要硬编码 " + NEEDLE + "someuser\\... 这类路径\n", encoding="utf-8"
        )

        legacy_dir = sandbox / "legacy"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "old.py").write_text(
            'BASE_DIR = Path(r"' + NEEDLE + 'someuser\\Desktop\\study")\n', encoding="utf-8"
        )

        print("=== 1. 含硬编码代码行的文件必须被抓到 ===")
        code_hits, _ = scan_roots([bad_dir])
        check("抓到违规代码行", len(code_hits) == 1, f"-> {code_hits}")

        print("=== 2. 只在注释里提到旧路径，不算违规 ===")
        code_hits2, doc_hits2 = scan_roots([comment_dir])
        check("注释不算代码违规", not code_hits2, f"-> {code_hits2}")
        check("注释被单独统计", len(doc_hits2) == 1, f"-> {doc_hits2}")

        print("=== 3. legacy/ 里的历史脚本按设计被跳过 ===")
        code_hits3, _ = scan_roots([sandbox])
        names = [h.split(":")[0] for h in code_hits3]
        check("只命中 violates.py", names == ["violates.py"], f"-> {names}")

        print("=== 4. 真实仓库当前必须为干净 ===")
        code_hits4, doc_hits4 = scan_roots([ROOT])
        check("真实仓库无硬编码代码行", not code_hits4, f"-> {code_hits4}")
        print(f"         （真实仓库注释中提及 {len(doc_hits4)} 处，属正常）")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[PASSED] 硬编码路径扫描确实有效（非空断言）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
