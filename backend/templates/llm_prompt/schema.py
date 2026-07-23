from backend.templates.llm_prompt._common import AnalysisTask, parse_json


def _parse_schema_analysis(raw: str) -> dict:
    """Schema 分析专用解析器"""
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime

        parsed["generated_at"] = datetime.now().isoformat()
    return parsed


TASK_SCHEMA_ANALYSIS = AnalysisTask(
    name="schema_analysis",
    description="数据库 Schema 合规性分析",
    prompt_template="""你是一个数据库 Schema 分析专家。请分析以下数据库 Schema 的合规性。

## 目标版本
{expected_version}

## Schema 元数据
{schema_metadata}

## 输出要求（严格 JSON 格式）
请只输出 JSON：

```json
{{
  "compliance_score": 0.95,
  "missing_tables": ["缺失的表"],
  "missing_columns": [
    {{
      "table": "表名",
      "column": "缺失列名",
      "expected_type": "期望类型"
    }}
  ],
  "orphan_tables": ["孤立表（无FK关联）"],
  "suggestions": ["优化建议"],
  "migration_sql": ["修复SQL语句"]
}}
```

注意：只输出 JSON""",
    parser=_parse_schema_analysis,
    max_tokens=2048,
    input_truncate=8000,
    feature_flag="enhance_analysis",
)
