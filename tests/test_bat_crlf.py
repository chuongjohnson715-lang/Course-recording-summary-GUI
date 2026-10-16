"""启动器回归测试：.bat 文件必须是 CRLF 行尾。

背景：cmd.exe 的批处理解析器要求 CRLF。曾因重写 bat 时用了 LF-only 行尾，
导致双击启动完全失败——cmd 把内容拆成碎片执行（每行开头字符被吞），
而当时只测了组件没测启动器本身，漏检了两天。

本测试防止再次发生：只要任何一个 .bat 含有裸 LF，立即失败。

运行：
    python tests/test_bat_crlf.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


def main() -> int:
    bats = [
        ROOT / "course-notes-desktop" / "start.bat",
        ROOT / "启动监控.bat",
    ]

    for bat in bats:
        print(f"--- {bat.name} ---")
        if not bat.exists():
            check(f"{bat.name} 存在", False)
            continue
        raw = bat.read_bytes()
        lf_only = raw.count(b"\n")
        crlf = raw.count(b"\r\n")
        bare_lf = lf_only - crlf
        check(f"{bat.name} 无裸 LF（全部 CRLF）", bare_lf == 0,
              f"-> CRLF={crlf}, 裸LF={bare_lf}")
        check(f"{bat.name} 非 ASCII 字节为零（cmd 用 OEM 码页解析）",
              all(b < 128 for b in raw),
              f"-> 含 {sum(1 for b in raw if b >= 128)} 个非 ASCII 字节")

    # .gitattributes 必须声明 bat 用 CRLF，防止以后工具/git 再写坏
    ga = ROOT / ".gitattributes"
    if ga.exists():
        content = ga.read_text(encoding="utf-8")
        check(".gitattributes 有 *.bat eol=crlf 规则", "eol=crlf" in content and "*.bat" in content,
              f"-> {content[:80]!r}")
    else:
        check(".gitattributes 存在并有 bat 规则", False, "-> 文件不存在")

    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        print("\n修复方法：把上面列出的 bat 用 CRLF 重写（PowerShell：")
        print("  $c=[IO.File]::ReadAllText($p).Replace(\"`r`n\",\"`\n\").Replace(\"`\n\",\"`r`n\");")
        print("  [IO.File]::WriteAllText($p,$c,[Text.Encoding]::ASCII)  ）")
        return 1
    print("[PASSED] 启动器 CRLF 与编码检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
