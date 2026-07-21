from prompts._common import AnalysisTask, parse_json

def _parse_file_parse(raw: str) -> dict:
    """文件解析专用解析器"""
    return parse_json(raw)

TASK_FILE_PARSE = AnalysisTask(
    name="file_parse",
    description="Markdown 对话记忆文件解析",
    prompt_template="""你是一个专业的文档解析 AI 助手。请将以下 Markdown 格式的对话记忆文件拆分为独立的对话条目。

## 文件信息
- 文件名: {filename}

## 文件内容
{content}

## 输出要求
请严格按照以下 JSON 格式输出:

```json
{{
  "conversations": [
    {{
      "time": "对话时间 (格式: HH:MM 或 00:00)",
      "topic": "对话主题概括（100字以内）",
      "content": "该条对话的完整原文内容",
      "source": "对话来源: codebuddy/cursor/windsurf/trae/unknown"
    }}
  ]
}}
```

解析规则：
1. 每个对话条目应该是完整的语义单元
2. 如果文件中包含 source 或 client 标记，提取到 source 字段
3. 如果无法明确拆分，将整个文件作为一条对话
4. 保留原文的完整性，不要省略关键信息
5. 只输出 JSON，不要其他文字""",
    parser=_parse_file_parse,
    max_tokens=2048,
    input_truncate=8000,
    feature_flag="enhance_file_parsing",
)