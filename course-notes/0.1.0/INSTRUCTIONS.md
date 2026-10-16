# 课堂笔记助手（Course Notes Assistant）

课堂录音处理工作流插件，由两个相互衔接的 skill 组成：

1. **transcript-cleaner（转录清洗）**：按课表给录音改名 → 清洗 ASR 转录（去口水词、修正同音错字、保留时间戳锚点、标记低置信度片段）→ 产出标准清洗稿。
2. **course-assessment-analyzer（课程重点分析）**：从清洗稿提取考点/小测/作业/老师强调/通知/知识点 → 输出结构化 JSON 与摘要 → 按科目追加到 Notion 长期归档。

## 典型用途

- 课堂录音转录后需要"删掉口水词、修正错别字、按主题分好段" → 用 `transcript-cleaner`。
- 想快速知道这节课考什么、有什么作业、待确认哪些事情 → 用 `course-assessment-analyzer`。
- 希望每节课的沉淀（清洗稿 + 考点分析）都归到 Notion 里对应科目下，长期累积 → 两个 skill 叠加。

## Skill 命名说明

插件展示名（在插件列表/界面中显示）为**中文**「课堂笔记助手」；内部 skill 的标识符采用英文 slug（`transcript-cleaner`、`course-assessment-analyzer`），这是插件命名空间与路径的要求，无法用中文。中文字面说明均已写在 description / i18n 中。

## 纳入的默认信息

- 开学日 `SEMESTER_START = 2026-08-31`（2026-2027 学年第 1 学期，周一），用于按周计算"第几周"并过滤课表周次。
- 课表来源：`study/课表.xls`（周课表 + 分周排课）；转录脚本会据此给录音改名。