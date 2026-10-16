# 课堂笔记助手（Course Notes Assistant）

把课堂录音自动变成结构化笔记：**丢一个录音文件进 `sounds/`，程序自动改名 → 转录 → 清洗 → 分析 →（可选）归档到 Notion**。

本项目提供两条链路，共用同一套核心代码与配置：

| 链路 | 入口 | 形态 | 适合 |
|------|------|------|------|
| **命令行监控** | `启动监控.bat` / `entry/watch.py` | 常驻监控目录，来一个跑一个 | 挂机批量处理 |
| **桌面程序** | `course-notes-desktop/start.bat` | Tkinter 图形界面，任务列表 + 进度 | 想看得见每一步 |

---

## ⚠️ 关于本仓库不含任何数据

本仓库**只包含程序代码**，不包含任何真实录音、转录文本、课堂笔记或课表。
`config/settings.yaml` 里的学期开始日期是**示例值**，请按自己的情况修改。

请自备输入：把录音放进 `sounds/`，然后运行程序。

---

## 目录结构

```
study/
├─ 启动监控.bat                 # 命令行链路启动器（双击即可）
├─ requirements.txt             # 全项目依赖
├─ .env.example                 # 凭证模板 -> 复制成 .env
├─ config/                      # 唯一配置真源
│   ├─ paths.py                 #   路径解析（自动推导，不含硬编码用户名）
│   └─ settings.yaml            #   业务参数（学期、模型、重试……）
├─ core/                        # 命令行链路的核心
│   ├─ schedule.py              #   按课表把 20261008_100444.m4a 改成「大学物理-2026-10-08.m4a」
│   ├─ transcribe.py            #   SenseVoice 转录
│   ├─ lock.py                  #   跨进程锁（防止两个入口抢同一个 sounds/）
│   └─ retry.py                 #   瞬时故障重试
├─ entry/watch.py               # 命令行监控入口
├─ course-notes-desktop/        # 桌面程序（Tkinter）
│   ├─ start.bat
│   ├─ main.py
│   └─ src/                     #   ui / engine / db / cleaner / analyzer / notion_client …
├─ course-notes/0.1.0/          # 清洗与分析用的提示词（skill 定义）
│   └─ skills/
├─ tests/                       # 回归测试（见下方「测试」）
└─ tools/                       # 辅助脚本 + 自检
    ├─ selfcheck.py             #   一键自检（不需要 API Key）
    └─ run_tests.py             #   跑 tests/ 下全部测试
```

---

## 快速开始

### 1. 准备 Python 环境

需要 **Python 3.10+**。在项目根目录执行：

```bat
python -m venv .venv --system-site-packages
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> `--system-site-packages` 是为了复用系统里已装好的 torch 等大包；
> 如果你的系统 Python 里没有这些包，去掉这个参数也能用，只是下载久一些。

### 2. 配置凭证（可选）

```bat
copy .env.example .env
```

编辑 `.env`，把 `OPENAI_API_KEY` 换成你自己的
[DeepSeek Key](https://platform.deepseek.com/api_keys)。

**不填也能用**：改名和转录照常跑，只在「清洗」这一步停下并提示。

### 3. 运行

**命令行链路**：把录音丢进 `sounds/`，双击 `启动监控.bat`。

**桌面链路**：双击 `course-notes-desktop\start.bat`。

---

## 工作流程

```
sounds/xxx.m4a
   │
   ├─ 1. 改名    按 课表.xls 匹配课程与上课时间 -> 大学物理-2026-10-08.m4a
   ├─ 2. 转录    SenseVoice -> txt/…_sensevoice.txt
   ├─ 3. 清洗    LLM 去口语、纠错 -> course-notes/outputs/…-cleaned.md
   ├─ 4. 分析    提取作业/考试重点/通知 -> …-analysis.json + …-summary.md
   └─ 5. 归档    推送到 Notion（可选，未配置则跳过）
```

产物分两处，互不覆盖：

- `txt/` —— 转录原文
- `course-notes/outputs/` —— 清洗稿、分析、摘要
  （桌面程序额外写到 `outputs/desktop/` 子目录）

---

## 配置说明

### 课表（改名依据）

程序按以下顺序寻找课表，找到第一个就用：

```
课表.xls / 课表.xlsx / 课表.txt   （项目根目录，你自己的）
课表 .txt / 课表.txt              （项目根的上一级，即桌面）
课表.example.xls                  （仓库自带的虚构示例，优先级最低）
```

**仓库自带 `课表.example.xls`**（全部为虚构的「示例大学 / 李示例」数据），
所以 clone 下来就能立刻跑通改名功能。想要真实效果，把自己的课表
另存为 `.xls` 放到项目根目录并命名为 `课表.xls`，它会自动覆盖示例。

> `.xls` 是硬性要求：解析用的是 `xlrd`，它读不了 `.xlsx`。
> 用 Excel / WPS 打开后「另存为 → Excel 97-2003 工作簿(*.xls)」即可。

**课表格式**（`core/schedule.py` 按此解析）：

- 第 3 行是 `星期一` ~ `星期日` 表头
- 第 4 行起，第 1 列为 `第一大节` + `01、02小节` + `08:00~09:50`
- 课程格内：先写课程名，再写 `教师;周次周;节次`（如 `李示例;1-16周;1-2节`）
- 教室行（含「楼」「室」「线上」）会被自动跳过

**没有课表也能跑**：改名会跳过，文件按原名继续转录。

> 重新生成示例课表：`.venv\Scripts\python.exe tools\make_example_schedule.py`
> 校验它可用：`.venv\Scripts\python.exe tools\verify_example_schedule.py`

### `config/settings.yaml`

| 配置项 | 含义 |
|--------|------|
| `semester.start` | 学期第一周的周一，用于推算「第几周」 |
| `transcribe.model` | SenseVoice 模型名，默认 `iic/SenseVoiceSmall` |
| `transcribe.segment_sec` | 分段秒数，过大爆内存，过小丢上下文 |
| `watch.process_existing_on_start` | 启动时是否处理 `sounds/` 里已有的文件 |
| `retry.*` | 瞬时故障（网络抖动、Notion 限流）重试次数与间隔 |

把项目整个复制到别的盘符/用户名下也能直接跑，**不需要改任何代码**：
所有路径都由 `config/paths.py` 从文件自身位置推导。
也可以用环境变量 `COURSE_NOTES_BASE_DIR` 把数据指到别处。

---

## 测试

```bat
.venv\Scripts\python.exe tools\selfcheck.py     # 一键自检，不需要 API Key
.venv\Scripts\python.exe tools\run_tests.py     # 跑 tests/ 下全部回归测试
```

`tests/` 里的用例都是**隔离沙箱**形式：用临时目录当项目根，
绝不碰你真实的 `sounds/`、`tasks.db` 和笔记产物，可以放心跑。

覆盖的真实踩过的坑包括：

- 双击 bat 报「不是内部或外部命令」（bat 必须 CRLF 行尾）
- 引擎异常后永久卡死
- 失败重试成功后残留旧错误文本
- 两个入口同时抢 `sounds/` 导致产物互相覆盖
- 清洗稿出现两个 YAML front matter

---

## FAQ

**Q：双击 `.bat` 闪一下就没了？**
A：窗口里有报错信息。常见原因是没建 `.venv` 或没装依赖，
启动器会列出它试过的解释器路径和修复命令。

**Q：`ModuleNotFoundError: No module named 'torch'`**
A：依赖没装全，重跑第 1 步。注意 `torch` 必须显式安装。

**Q：桌面程序报 `No module named 'tkinter'`**
A：`tkinter` 不在 pip 里。请换用 python.org 官方安装包重装 Python（安装时勾选 tcl/tk）。

**Q：转录很慢 / 爆内存？**
A：调小 `settings.yaml` 里的 `transcribe.segment_sec`。

**Q：清洗这一步报「LLM 未配置」？**
A：没填 `.env` 里的 `OPENAI_API_KEY`。这是预期行为，前两步的产物不受影响。

---

## 隐私提醒

**不要把你自己的录音、转录、课表、笔记提交到公开仓库。**
这些既是隐私（真人姓名、学校、谈话内容），也会让仓库迅速膨胀
（本项目清理前，历史里曾因 3 个录音文件达到 579 MB）。

`.gitignore` 已经默认排除 `sounds/`、`txt/`、`course-notes/outputs/`、
`课表.xls`、`.env` 与各类凭证文件。提交前请用下面命令确认：

```bat
git status
git ls-files | findstr /i "sounds txt 课表 outputs"
```

第二条**应当没有输出**。若有输出，说明有敏感文件被跟踪了，
执行 `git rm --cached <文件>` 只把它从版本控制移除（本地文件不受影响）。

---

## 免责声明

课堂录音与转录可能涉及教师、同学的肖像权与隐私权。
请仅用于个人学习，并在录音前遵守所在学校的规定与当地法律；
**请勿将任何真实课堂数据上传到公开仓库或第三方服务。**

---

## 许可

暂未指定开源许可证。如需他人自由使用，建议添加 [MIT](https://choosealicense.com/licenses/mit/)。
