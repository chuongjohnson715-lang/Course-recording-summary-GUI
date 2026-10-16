"""【已停用】原命令行监控脚本。

本文件的功能已完全合并进 ``core/``，请改用新入口：

    python entry/watch.py            # 等价于原来的 python watch_and_transcribe.py
    （Windows 上更简单：双击项目根目录的  启动监控.bat ）

为什么停用
----------
* 改名逻辑现在只有一份：``core/schedule.py``（原实现与本文件曾各写一遍）
* 转录逻辑现在只有一份：``core/transcribe.py``（原实现在三处重复）
* 路径不再写死 ``C:\\Users\\<用户名>\\...``，改由 ``config/paths.py`` 推导

完整旧实现已原样保存在 ``legacy/watch_and_transcribe.py``，仅作历史参考。

本文件保留为「显式报错的壳」，目的是：如果还有地方 import 它，或有人误运行它，
能立刻看到明确指引，而不是跑起一份会漂移的旧逻辑。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_NEW = _ROOT / "entry" / "watch.py"

_MSG = f"""
[已停用] sensevoice/watch_and_transcribe.py 已被 core/ 取代。

请改用：
    双击  {_ROOT / '启动监控.bat'}
或   python "{_NEW}"

旧实现存档于： {_ROOT / 'legacy' / 'watch_and_transcribe.py'}
"""


def _refuse(*_args, **_kwargs):
    raise RuntimeError(_MSG)


# 任何从本模块导入旧函数名的行为都会看到明确指引，而不是静默拿到一份旧逻辑
find_schedule_file = _refuse
parse_weeks_str = _refuse
load_schedule = _refuse
load_schedule_xls = _refuse
rename_by_schedule = _refuse
parse_recording_time = _refuse
safe_name = _refuse
fmt_time = _refuse
semester_week = _refuse
clean_text = _refuse
load_audio = _refuse
transcribe_segment = _refuse
transcribe_long_audio = _refuse
process_file = _refuse
is_audio = _refuse
is_stable = _refuse
main = _refuse


if __name__ == "__main__":
    print(_MSG)
    sys.exit(2)
