"""
DataBuilder — 统一数据构造层 (v9.10.1)
======================================
统一 JSON 解析/截断/step_input/task_payload/上下文组装。
消除散落在 Engine 各处的重复 _build_xxx 方法。
"""

import json
import logging
from datetime import datetime
from typing import Any

from backend.business.conversation_mgr.constants import TRUNC_RULES

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 工具方法
# ══════════════════════════════════════════════════════════


def safe_json_parse(val: Any, default: Any = None) -> Any:
    """安全 JSON 解析"""
    if val is None:
        return default if default is not None else {}
    if isinstance(val, (list, dict)):
        return val
    if not isinstance(val, str):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def truncate(key: str, value: Any) -> str:
    """统一截断"""
    max_len = TRUNC_RULES.get(key, 50_000)
    return (str(value) if value else "")[:max_len]


def safe_json_dumps(obj: Any) -> str:
    """安全 JSON 序列化"""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(str(obj), ensure_ascii=False)


# ══════════════════════════════════════════════════════════
# Step Input / Task Payload 构建
# ══════════════════════════════════════════════════════════


class DataBuilder:
    """统一数据构造器"""

    @staticmethod
    def build_step_input(
        step_name: str = "",
        step_type: str = "general",
        content: str = "",
        files_changed: str = "",
        symptom: str = "",
        root_cause: str = "",
        solution: str = "",
        knowledge_points: str = "",
        user_question: str = "",
        client_request_id: str = "",
        ai_reasoning: str = "",
        user_requirement: str = "",
        commands_executed: str = "",
    ) -> dict[str, Any]:
        """构建 step_input 字典"""
        return {
            "step_name": step_name,
            "step_type": step_type,
            "content": truncate("content", content),
            "files_changed": safe_json_parse(files_changed, []),
            "symptom": truncate("symptom", symptom),
            "root_cause": truncate("root_cause", root_cause),
            "solution": truncate("solution", solution),
            "knowledge_points": safe_json_parse(knowledge_points, []),
            "user_question": truncate("user_question", user_question),
            "client_request_id": client_request_id or "",
            "ai_reasoning": truncate("ai_reasoning", ai_reasoning),
            "user_requirement": truncate("user_requirement", user_requirement),
            "commands_executed": truncate("commands", commands_executed),
            "recorded_at": datetime.now().isoformat(),
        }

    @staticmethod
    def build_task_payload(
        conversation_id: str,
        step_id: str,
        step_name: str = "",
        step_type: str = "general",
        content: str = "",
        knowledge_points: str = "",
        files_changed: str = "",
        symptom: str = "",
        root_cause: str = "",
        solution: str = "",
        ai_reasoning: str = "",
        user_requirement: str = "",
        commands_executed: str = "",
    ) -> dict[str, Any]:
        """构建任务队列 payload"""
        return {
            "conversation_id": conversation_id,
            "step_id": step_id,
            "step_name": step_name,
            "step_type": step_type,
            "content": truncate("content", content),
            "knowledge_points": safe_json_parse(knowledge_points, []),
            "files_changed": safe_json_parse(files_changed, []),
            "symptom": truncate("symptom", symptom),
            "root_cause": truncate("root_cause", root_cause),
            "solution": truncate("solution", solution),
            "ai_reasoning": truncate("ai_reasoning", ai_reasoning),
            "user_requirement": truncate("user_requirement", user_requirement),
            "commands_executed": truncate("commands", commands_executed),
        }

    @staticmethod
    def build_finalize_context(
        conversation_id: str,
        conv_meta: dict[str, Any],
        project_context: str,
        ai_summary: str = "",
        steps: list[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """构建 finalize 子任务共享上下文"""
        topic = conv_meta.get("topic", "") or ""
        system_id = conv_meta.get("system_id", "default") or "default"
        client = conv_meta.get("client", "unknown") or "unknown"
        user_raw_input = conv_meta.get("user_raw_input", "") or ""
        self_reflection = ai_summary or conv_meta.get("self_reflection", "") or ""
        ai_analysis_from_db = conv_meta.get("ai_analysis", "") or ""

        # 聚合 summary + steps_summary
        summary_parts = []
        steps_summary = []
        for s in steps or []:
            input_raw = s.get("input_data", "")
            if input_raw:
                input_dict = safe_json_parse(input_raw, {})
                content = input_dict.get("content", "")
                if content:
                    summary_parts.append(f"[{s.get('step_name', '')}]: {content[:500]}")
            step_info = {
                "name": s.get("step_name", ""),
                "type": s.get("step_type", ""),
                "status": s.get("status", ""),
                "created_at": s.get("created_at", ""),
            }
            output = s.get("output_data", "")
            if output:
                output_dict = safe_json_parse(output, {})
                step_info["thinking_patterns"] = output_dict.get("thinking_patterns", [])
                step_info["complexity"] = output_dict.get("complexity_level", "")
            steps_summary.append(step_info)
        summary = "\n".join(summary_parts)

        return {
            "conversation_id": conversation_id,
            "topic": topic,
            "system_id": system_id,
            "client": client,
            "user_raw_input": user_raw_input,
            "project_context": project_context,
            "summary": summary,
            "self_reflection": self_reflection,
            "user_traits": {},
            "key_decisions": [],
            "steps_summary": steps_summary,
            "ai_analysis": ai_analysis_from_db,
            "ai_summary": ai_summary,
        }

    @staticmethod
    def extract_user_traits_from_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
        """从步骤中提取 user_traits"""
        user_traits = {}
        for tr in steps or []:
            input_raw = tr.get("input_data", "")
            if input_raw:
                input_dict = safe_json_parse(input_raw, {})
                ut = input_dict.get("user_traits", {})
                if ut and isinstance(ut, dict):
                    for k, v in ut.items():
                        if k not in user_traits:
                            user_traits[k] = v
        return user_traits

    @staticmethod
    def extract_files_changed_from_steps(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
        """从步骤中提取 files_changed 信号"""
        tech_signals = []
        seen_files = set()
        for s in steps or []:
            sd = safe_json_parse(s.get("input_data", "{}"), {})
            fc = sd.get("files_changed", "")
            if fc:
                fc_list = (
                    json.loads(fc)
                    if isinstance(fc, str)
                    else (fc if isinstance(fc, list) else [fc])
                )
                for f in fc_list:
                    if f and f not in seen_files:
                        seen_files.add(f)
                        tech_signals.append({"file": f, "type": "file_touched"})
        return tech_signals


# ══════════════════════════════════════════════════════════
# 模块级单例（线程安全）
# ══════════════════════════════════════════════════════════

_builder_instance: DataBuilder | None = None


def get_data_builder() -> DataBuilder:
    """获取 DataBuilder 单例"""
    global _builder_instance
    if _builder_instance is None:
        _builder_instance = DataBuilder()
    return _builder_instance
