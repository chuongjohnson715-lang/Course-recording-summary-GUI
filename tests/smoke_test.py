"""集成冒烟测试：验证环境修复与重构后的关键路径真的能跑。

不依赖网络、不调用 LLM、不加载 SenseVoice 模型，只验证：
  1. 桌面链路整条 import 链通（含 core 合并后的 shim）
  2. ffmpeg 能真正解码出音频（C-10：且失败时会报错而不是静默空结果）
  3. 锁能互斥（C-6）
  4. 桌面输出目录与 Agent 输出目录已分开（C-8）
  5. 重试机制按预期工作（C-11）

运行：
    python tests/smoke_test.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "course-notes-desktop"
for p in (str(ROOT), str(DESKTOP)):
    if p not in sys.path:
        sys.path.insert(0, p)

sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        failures.append(label)


def test_imports() -> None:
    print("\n=== 1. import 链 ===")
    try:
        from config import paths, settings  # noqa: F401
        from core import lock, retry, schedule, transcribe  # noqa: F401
        check("config / core 可导入", True)
    except Exception as exc:  # noqa: BLE001
        check("config / core 可导入", False, f"-> {type(exc).__name__}: {exc}")
        return

    # 桌面链路的 shim 必须仍然把老名字暴露出来
    try:
        from src import config as dconfig
        from src.scheduler import rename_by_schedule  # noqa: F401
        from src.transcriber import Transcriber  # noqa: F401
        check("桌面 src shim 可导入", True)
    except Exception as exc:  # noqa: BLE001
        check("桌面 src shim 可导入", False, f"-> {type(exc).__name__}: {exc}")
        return

    try:
        from src.engine import ProcessingEngine  # noqa: F401
        check("engine 可导入（含 FileLock/retry 接线）", True)
    except Exception as exc:  # noqa: BLE001
        check("engine 可导入", False, f"-> {type(exc).__name__}: {exc}")

    check("BASE_DIR 由文件位置推导",
          paths.BASE_DIR == Path(__file__).resolve().parent.parent,
          f"-> {paths.BASE_DIR}")
    check("课表候选不再出现桌面绝对路径写法",
          all(str(p).startswith(str(paths.BASE_DIR)) or str(p).startswith(str(paths.BASE_DIR.parent))
              for p in paths.SCHEDULE_CANDIDATES))

    # C-7 的真正判据：全仓 .py 里不再写死 C:\Users\... 绝对路径。
    # 注意（原实现的两个缺陷，已修）：
    #   1) 原来只看 config/paths.py 一个文件，改别的文件它察觉不到 -> 现在全仓扫描
    #   2) 原来把以 # 开头的行排除掉，而唯一的命中恰好是文件头注释里的说明文字，
    #      于是这个断言永远为真（vacuous）。现在改为只排除「纯注释/文档字符串行」，
    #      并单独统计，真正的代码行出现硬编码就会失败。
    skip_parts = (".venv", "\\venv\\", "__pycache__", "\\legacy\\", "\\archive\\", "\\.git\\", "\\.tmp\\")
    # 用拼接方式构造特征串，并让本文件的断言文案也走拼接，
    # 这样本文件里不存在该字面量，因此可以（也应当）扫描自己，不留盲区。
    needle = "C:" + "\\" + "Users" + "\\"
    code_hits: list[str] = []
    doc_hits: list[str] = []
    root = Path(__file__).resolve().parent.parent
    for py in root.rglob("*.py"):
        sp = str(py)
        if any(part in sp for part in skip_parts):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if needle not in line:
                continue
            stripped = line.strip()
            # 注释行、或位于文档字符串/说明里的行 —— 归为文档提及
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                doc_hits.append(f"{py.name}:{i}")
            else:
                code_hits.append(f"{py.name}:{i} -> {stripped}")

    check("全仓 .py 无硬编码 " + needle + " 代码行", not code_hits,
          "-> " + "; ".join(code_hits))
    # 文档里提到旧路径是允许的（属于说明文字），但打印出来便于人工确认不是漏网之鱼
    print(f"         （文档/注释中提及旧路径 {len(doc_hits)} 处，属正常说明文字）")


def test_ffmpeg() -> None:
    print("\n=== 2. ffmpeg 解码（C-10）===")
    from core.transcribe import FFmpegError, load_audio, resolve_ffmpeg

    try:
        exe = resolve_ffmpeg()
        check("能定位 ffmpeg", True, f"-> {exe}")
    except FFmpegError as exc:
        check("能定位 ffmpeg", False, f"-> {exc}")
        return

    tmpdir = Path(tempfile.mkdtemp(prefix="cn_smoke_"))
    wav = tmpdir / "tone.wav"
    gen = subprocess.run(
        [exe, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-ar", "16000", "-ac", "1", str(wav)],
        capture_output=True,
    )
    if gen.returncode != 0 or not wav.exists():
        check("生成测试音频", False, f"-> {gen.stderr[:200]!r}")
        return
    check("生成测试音频", True)

    try:
        audio, sr = load_audio(wav)
        check("解码出非空音频", len(audio) > 0, f"-> {len(audio)} samples @ {sr}")
    except Exception as exc:  # noqa: BLE001
        check("解码出非空音频", False, f"-> {type(exc).__name__}: {exc}")

    # 故意喂一个坏文件：必须抛 FFmpegError，而不是返回空数组
    bad = tmpdir / "broken.m4a"
    bad.write_bytes(b"this is definitely not audio")
    try:
        load_audio(bad)
        check("坏文件必须报错（不再静默空输出）", False, "-> 竟然没抛异常")
    except FFmpegError:
        check("坏文件必须报错（不再静默空输出）", True)
    except Exception as exc:  # noqa: BLE001
        check("坏文件必须报错（不再静默空输出）", False, f"-> 抛了 {type(exc).__name__}")

    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_lock() -> None:
    print("\n=== 3. 监控锁互斥（C-6）===")
    from core.lock import FileLock

    lock_path = ROOT / ".tmp" / "smoke.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.unlink(missing_ok=True)

    a = FileLock(lock_path, mode="a")
    b = FileLock(lock_path, mode="b")
    check("第一个锁能拿到", a.acquire())
    check("第二个锁被拒绝", not b.acquire())
    check("拒绝信息含持有者", "pid=" in b.describe_holder())
    a.release()
    check("释放后第二个能拿到", b.acquire())
    b.release()
    check("释放后锁文件已清理", not lock_path.exists())


def test_outputs_separated() -> None:
    print("\n=== 4. 输出目录分离（C-8）===")
    from config import paths
    from src import config as dconfig

    check("桌面输出 != Agent 输出", dconfig.OUTPUT_DIR != dconfig.AGENT_OUTPUT_DIR,
          f"-> {dconfig.OUTPUT_DIR} vs {dconfig.AGENT_OUTPUT_DIR}")
    check("桌面输出在 Agent 输出之下", dconfig.OUTPUT_DIR.parent == dconfig.AGENT_OUTPUT_DIR)
    check("桌面输出目录名为 desktop", dconfig.OUTPUT_DIR.name == "desktop")
    check("Agent 原输出目录未被改动",
          paths.OUTPUTS_DIR == paths.BASE_DIR / "course-notes" / "outputs",
          f"-> {paths.OUTPUTS_DIR}")
    dconfig.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    check("桌面输出目录可创建", dconfig.OUTPUT_DIR.is_dir())


def test_retry() -> None:
    print("\n=== 5. 重试机制（C-11）===")
    from core.retry import retry_call

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    try:
        result = retry_call(flaky, attempts=3, delay=0, backoff=1)
        check("第 3 次成功即返回", result == "ok" and calls["n"] == 3, f"-> {result}, {calls['n']} calls")
    except Exception as exc:  # noqa: BLE001
        check("第 3 次成功即返回", False, f"-> {type(exc).__name__}: {exc}")

    def always_fail():
        raise RuntimeError("boom")

    try:
        retry_call(always_fail, attempts=2, delay=0, backoff=1)
        check("一直失败最终抛异常", False, "-> 没抛")
    except RuntimeError:
        check("一直失败最终抛异常", True)


def main() -> int:
    test_imports()
    test_ffmpeg()
    test_lock()
    test_outputs_separated()
    test_retry()

    print()
    if failures:
        print(f"[FAILED] {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[PASSED] 冒烟测试全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
