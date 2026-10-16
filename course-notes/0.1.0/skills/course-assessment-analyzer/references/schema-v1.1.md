# V1.1 Schema 完整定义与示例

本文件是 course-assessment-analyzer 的权威 Schema 文档。执行分析前必须加载。

## 顶层结构

```json
{
  "course_info": { "course_name": "", "date": "" },
  "assessment": {
    "final_exam": {
      "exam_date": "",
      "exam_format": "",
      "exam_scope": [],
      "explicit_exam_points": [],
      "possible_exam_points": [],
      "review_guidance": []
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

空值约定：`assessment` / `quizzes` / `assignments` / `teacher_emphasis` / `course_notices` / `pending_confirmations` 无内容时写字符串 `"无"`。

## 1. course_info（极简）

```json
{ "course_name": "大数据技术基础", "date": "2026-10-08" }
```

课程名与日期已知即可；清洗稿元信息已包含且用户不要求重复时，可整个省略。

## 2. assessment

本节课无任何考试/成绩信息 → `"assessment": "无"`。

有内容时：

```json
{
  "final_exam": {
    "exam_date": "2026-12-28（若老师未说则空字符串）",
    "exam_format": "闭卷（未提及则空字符串）",
    "exam_scope": ["第3章至第7章"],
    "explicit_exam_points": [
      {
        "topic": "MapReduce执行流程",
        "fact": "老师表示MapReduce执行流程会出现在期末考试中。",
        "judgment": "明确考试重点",
        "evidence": { "timestamp": "08:32-08:47", "quote": "这个地方期末考试会考。" },
        "confidence": "high"
      }
    ],
    "possible_exam_points": [
      {
        "topic": "Shuffle机制",
        "fact": "老师提到Shuffle机制去年考过，暗示今年仍可能涉及。",
        "judgment": "可能考试重点",
        "evidence": { "timestamp": "31:20-31:42", "quote": "这个大家注意一下，去年考试考过。" },
        "confidence": "medium"
      }
    ],
    "review_guidance": ["建议重点看课件第3章例题"]
  },
  "grading_rules": ["平时成绩占40%，期末占60%"]
}
```

### explicit vs possible 的判定

| 归入 explicit_exam_points | 归入 possible_exam_points |
|---------------------------|---------------------------|
| "期末会考"、"这是考点"、"必考" | "可能会考"、"去年考过"、"注意一下"（未明说考试） |
| 老师明确划定范围 | 从语气/上下文推断的考试指向 |
| 且 confidence ≠ low | 任何 confidence（含 low） |

老师只说"重要"没说"考试" → 不进 assessment，进 teacher_emphasis。

## 3. quizzes（极简）

```json
[
  {
    "status": "有",
    "content": "MapReduce基础知识测试",
    "deadline": "2026-10-08 23:59",
    "evidence": { "timestamp": "52:13-56:40", "quote": "今天晚上之前把这个小测完成。" },
    "confidence": "high"
  }
]
```

- 老师没说截止时间 → `"deadline": "未说明"`。**禁止推测截止时间。**
- 无小测 → `"quizzes": "无"`。

## 4. assignments（极简）

```json
[
  {
    "status": "有",
    "content": "完成实验一报告",
    "deadline": "2026-10-12",
    "submission": "学习通提交",
    "evidence": { "timestamp": "01:12:30-01:13:05", "quote": "下周一之前把实验一报告交到学习通。" },
    "confidence": "high"
  }
]
```

- `submission` 未提及 → `"未说明"`。
- 无作业 → `"assignments": "无"`。

## 5. teacher_emphasis

```json
[
  {
    "topic": "Shuffle机制",
    "fact": "老师强调Shuffle机制非常重要，要求大家理解。",
    "judgment": "老师明确强调重要",
    "evidence": { "timestamp": "31:20-31:42", "quote": "这个地方大家一定要理解。" },
    "confidence": "high"
  }
]
```

- **老师强调重要 ≠ 考试重点**，两个通道严格分离。
- 同一内容已进 explicit_exam_points 的，不再重复进 teacher_emphasis。
- 无 → `"teacher_emphasis": "无"`。

## 6. knowledge_points

```json
[
  {
    "topic": "MapReduce",
    "summary": "分布式计算模型，包含Map、Shuffle、Reduce等阶段。",
    "importance": "高"
  }
]
```

- `importance`（高/中/低）是 **AI 判断**，基于讲授时长、重复次数、老师语气。
- **importance 与考试判断（exam 相关）绝不能混**：importance 字段内禁止出现"考试重点"字样；考试指向只能来自老师原话并进入 assessment。
- importance 条目不需要 evidence 字段（它不是"影响成绩的事实判断"），但如果某知识点同时是考点，应在 assessment 中带证据出现。

## 7. course_notices

```json
[
  {
    "content": "下周课程调整到周五",
    "judgment": "课程安排变更",
    "evidence": { "timestamp": "01:20:10-01:20:30", "quote": "下周三我们不上课，调到周五。" },
    "confidence": "high"
  }
]
```

覆盖：停课/调课/换教室、实验、答辩、分组、课程论文、考试安排、老师要求关注群通知等。无 → `"无"`。

## 8. pending_confirmations（必须保留）

```json
[
  {
    "content": "实验报告具体提交要求",
    "judgment": "课堂中未明确，需要查看后续通知",
    "evidence": { "timestamp": "01:25:10-01:25:30", "quote": "具体要求我之后发群里。" },
    "confidence": "high"
  }
]
```

- 作用：防止 AI 自作聪明，把"老师没说清"的事显式挂起。
- 无 → `"无"`。

## 完整输出示例（一节课的真实形态）

```json
{
  "course_info": { "course_name": "大数据技术基础", "date": "2026-10-08" },
  "assessment": {
    "final_exam": {
      "exam_date": "",
      "exam_format": "",
      "exam_scope": [],
      "explicit_exam_points": [
        {
          "topic": "MapReduce执行流程",
          "fact": "老师表示MapReduce执行流程会出现在期末考试中。",
          "judgment": "明确考试重点",
          "evidence": { "timestamp": "08:32-08:47", "quote": "这个地方期末考试会考。" },
          "confidence": "high"
        }
      ],
      "possible_exam_points": [
        {
          "topic": "Shuffle机制",
          "fact": "老师提到Shuffle机制去年考过。",
          "judgment": "可能考试重点",
          "evidence": { "timestamp": "31:20-31:42", "quote": "这个大家注意一下，去年考试考过。" },
          "confidence": "medium"
        }
      ],
      "review_guidance": []
    },
    "grading_rules": []
  },
  "quizzes": [
    {
      "status": "有",
      "content": "MapReduce基础知识测试",
      "deadline": "2026-10-08 23:59",
      "evidence": { "timestamp": "52:13-56:40", "quote": "今天晚上之前把这个小测完成。" },
      "confidence": "high"
    }
  ],
  "assignments": "无",
  "teacher_emphasis": "无",
  "knowledge_points": [
    { "topic": "MapReduce", "summary": "分布式计算模型，包含Map、Shuffle、Reduce阶段。", "importance": "高" },
    { "topic": "HDFS架构", "summary": "NameNode/DataNode主从架构与副本机制。", "importance": "中" }
  ],
  "course_notices": "无",
  "pending_confirmations": [
    {
      "content": "实验报告具体提交要求",
      "judgment": "课堂中未明确，需要查看后续通知",
      "evidence": { "timestamp": "01:25:10-01:25:30", "quote": "具体要求我之后发群里。" },
      "confidence": "high"
    }
  ]
}
```
