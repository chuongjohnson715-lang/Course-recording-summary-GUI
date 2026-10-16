---
name: course-assessment-analyzer
description: 分析课堂转录文本（清洗稿或原始稿），提取影响成绩的关键信息并输出 V1.1 结构化 JSON：考试信息（明确考点/可能考点）、课堂小测、作业、老师强调、知识点、课程通知、待确认事项。所有重要条目采用"事实+判断+证据+置信度"四层结构，证据含时间戳与原话。当用户提供课堂录音转录/清洗稿并要求提取课程重点、考试重点、作业、考核信息，或要求生成可导入 Notion 的课程分析 JSON 时使用（V1.1 规范）。
agent_created: true
---

# 课程重点与考核分析 Skill V1.1

## 核心原则

**少记录无用信息，多记录影响成绩的信息；所有重要判断必须有证据。**

三条铁律：

1. **无证据不记录。** 每个进入结果的条目必须附带证据（时间戳 + 老师原话）。凭"感觉重要"而无原话支撑的内容不得进入 assessment/quizzes/assignments。
2. **绝不编造。** 老师没说的截止时间写 `"未说明"`，不得推测；听不清的内容不得脑补；识别存疑的原话不得作为 high 置信度证据。
3. **判断与事实分离。** AI 的推断（importance）与老师的明确表达（exam 相关判断）是两个通道，绝不混淆。

## 输入

- **首选**：transcript-cleaner 产出的清洗稿（`*-cleaned.md`，带统一时间戳锚点）。
- 若用户直接给原始 ASR 转录且未清洗：先建议/执行 transcript-cleaner 清洗；用户明确跳过清洗时，直接分析但将所有依赖模糊片段的条目置信度降为 medium 或 low。

## 四层信息结构（每条重要信息统一采用）

```json
{
  "fact": "老师表示 MapReduce 执行流程会出现在期末考试中。",
  "judgment": "明确考试重点",
  "evidence": {
    "timestamp": "08:32-08:47",
    "quote": "这个地方期末考试会考。"
  },
  "confidence": "high"
}
```

- **fact（事实）**：老师实际上说了什么，一句话概括。
- **judgment（判断）**：Skill 根据老师的话判断该信息属于什么类别。
- **evidence（证据）**：转录中的具体时间区间 + 原话引用。时间戳必须与清洗稿锚点一致，quote 必须是转录原文（允许省略口水词），不得改写。
- **confidence（置信度）**：仅三档——`high` / `medium` / `low`。

### 置信度判定标准

| 档位 | 条件 |
|------|------|
| high | 老师明确表述 + 转录清晰 + 上下文完整 |
| medium | 老师表述明确但转录含 `[识别存疑]` 标记，或表述本身带不确定性（"可能会考"），或上下文不完整 |
| low | 片段含 `[听不清]`/`⚠️[低置信度片段]`，或只能靠推测还原语义 |

**硬规则：confidence 为 low 的信息不得进入 `explicit_exam_points`**，只能进 `possible_exam_points` 或 `pending_confirmations`。

## 输出 Schema（V1.1 收敛版）

完整字段定义与示例见 **references/schema-v1.1.md**，执行分析前加载该文件。顶层结构：

```json
{
  "course_info": { "course_name": "", "date": "" },
  "assessment": {
    "final_exam": {
      "exam_date": "", "exam_format": "", "exam_scope": [],
      "explicit_exam_points": [], "possible_exam_points": [], "review_guidance": []
    },
    "grading_rules": []
  },
  "quizzes": [],
  "assignments": [],
  "teacher_emphasis": [],
  "knowledge_points": [],
  "course_notices": [],
  "pending_confirmations": []
}
```

### 各模块要点

1. **course_info —— 极简**：只要 `course_name` 和 `date`。清洗稿元信息里已有且用户不需要重复时，整个 course_info 可省略。
2. **assessment**：本节课没有任何考试/成绩信息 → `"assessment": "无"`。考点严格区分 `explicit_exam_points`（老师明说会考/考过，judgment="明确考试重点"）与 `possible_exam_points`（老师暗示或往年考过等，judgment="可能考试重点"）。
3. **quizzes**：只记 有没有/内容/截止时间/证据。老师没说截止时间 → `"deadline": "未说明"`。没有 → `"quizzes": "无"`。
4. **assignments**：只记 内容/截止时间/提交方式/证据。没有 → `"assignments": "无"`。
5. **teacher_emphasis**：老师明确强调重要（"这个东西非常重要，一定要理解"）但**未提考试**的内容放这里，judgment="老师明确强调重要"。与考试重点严格分离，不得重复记录。没有 → `"无"`。
6. **knowledge_points**：本节课实际讲授的知识点，含 `topic`、`summary`（一两句）、`importance`（高/中/低，**这是 AI 判断**）。importance 绝不写成"考试重点"——考试指向只能来自老师原话并进 assessment。
7. **course_notices**：停课、调课、换教室、实验/答辩/分组安排、课程论文、关注群通知等。没有 → `"无"`。
8. **pending_confirmations**：老师说"具体要求发群里"、"之后再通知"等课堂未落地的信息，judgment="课堂中未明确，需要查看后续通知"。没有 → `"无"`。**此模块必须保留**，防止 Skill 自作聪明。

### 空值统一约定

- `assessment`、`quizzes`、`assignments`、`teacher_emphasis`、`course_notices`、`pending_confirmations` 无内容时一律写 `"无"`（字符串），不写空数组、不写 `mentioned: false` 之类的冗余字段。
- `knowledge_points` 一节课总有内容，正常为数组；极端情况下（如整节课是考试）才写 `"无"`。

## 分析流程

1. **加载 references/schema-v1.1.md**，确认字段定义与示例。
2. **通读清洗稿**，先扫全部 `[识别存疑]`、`[听不清]`、`⚠️[低置信度片段]` 标记，建立置信度地图。
3. **按模块逐块提取**：assessment → quizzes → assignments → teacher_emphasis → course_notices → pending_confirmations → knowledge_points。每条先写 evidence（时间戳+原话），再写 fact，再给 judgment 和 confidence。
4. **交叉检查**：
   - 同一内容不得同时出现在 explicit_exam_points 和 teacher_emphasis（说了考试的归前者）。
   - 每个 deadline 都能在证据原话中找到；找不到 → "未说明"。
   - low 置信度条目未进入 explicit_exam_points。
5. **输出两份产物**（命名沿用清洗稿前缀 `{课程名}-{日期}`）：
   - `{前缀}-analysis.json`：完整 V1.1 JSON（供 Notion/程序消费）。
   - `{前缀}-summary.md`：人读摘要，按以下顺序组织（表格优先）：
     - ⚠️ 待确认事项（最置顶，最容易漏）
     - 📌 作业与小测（内容 + 截止时间）
     - 🎯 考试重点（明确/可能分两栏，附时间戳）
     - 💡 老师强调
     - 📢 课程通知
     - 📚 本节知识点（带 importance）
6. **汇报**：简要说明提取了多少条考点/作业/待确认，指出哪些条目置信度偏低建议人工回听。

## Notion 归档（按科目长期更新，可选但推荐）

分析完成后，把本节课的沉淀按**科目**写进用户已连接的 Notion，让同一科目的多节课长期累积到同一处。
目标结构（自动维护）：

```
课堂笔记（顶层页）
 ├─ 大学物理（科目页，第一次出现该科目时创建）
 │    └─ 2026-10-08 周四（每次课新增一个日期页，标题含课程名+日期）
 ├─ 算法设计与分析（科目页）
 │    └─ 2026-10-09 ……
 └─ ……
```

执行规则（使用 Notion MCP 工具，如 `notion-search` / `notion-create-pages` / `notion-update-page`）：

1. **定位结果**：`notion-search` 搜「课堂笔记」找顶层归档页；不存在则新建（标题「课堂笔记」，内容留空）。
2. **定位科目页**：在「课堂笔记」下按 `course_info.course_name`（去掉课次编号，如 `大学物理（B）（2-2）` 归一为 `大学物理`）查找科目页。存在 → 作为本次归档的父页；不存在 → 以「课堂笔记」为父新建科目页。
3. **新增日期页**：在科目页下新建本次课的日期页，标题 `{yyyy-MM-dd} {星期} {课程主题}`。页面内容用 Notion Markdown 写入，按本 skill 的 summary 顺序组织：⚠️ 待确认 → 📌 作业与小测 → 🎯 考试重点 → 💡 老师强调 → 📢 课程通知 → 📚 知识点；每节用 `##` 标题，重要条目含时间戳与证据。
4. **结构化字段（可选增强）**：若用户后续想要能筛选/统计，可为科目或日期页补充属性（如日期、科目名），具体属性名先与用户确认再建库。
5. **汇报**：说明本节课归档到了 Notion 的哪个科目页，并提示"同一科目后续上课都会追加到该页"。
