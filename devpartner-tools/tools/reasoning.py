"""
🧠 推理与分析工具集 — 4 个工具

设计原则：
  - sequential_think：辅助 AI 进行结构化链式思考
  - generate_mindmap / generate_mindmap_from_tree：生成 Mermaid 思维导图代码
  - list_mindmaps：列出内置模板（静态信息）
"""

from typing import Dict, Any
from datetime import datetime


def sequential_think(thought: str, thought_number: int, total_thoughts: int,
                     next_thought_needed: bool = True) -> Dict[str, Any]:
    """
    链式思考推理 — 辅助 AI 结构化思维

    支持分步拆解复杂问题，记录每一步的思考过程。

    Args:
        thought: 当前思考内容
        thought_number: 当前思考步骤编号
        total_thoughts: 总思考步骤数
        next_thought_needed: 是否还需要下一步思考

    Returns:
        {thought_number, total_thoughts, next_thought_needed, thought, summary, timestamp, progress_percent}
    """
    timestamp = datetime.now().isoformat()
    summary = thought[:100] + "..." if len(thought) > 100 else thought

    return {
        "thought_number": thought_number,
        "total_thoughts": total_thoughts,
        "next_thought_needed": next_thought_needed,
        "thought": thought,
        "summary": summary,
        "timestamp": timestamp,
        "progress_percent": round((thought_number / total_thoughts) * 100, 1)
        if total_thoughts > 0 else 0
    }


def generate_mindmap(title: str, data: Dict[str, Any],
                     output_format: str = "mermaid") -> Dict[str, Any]:
    """
    生成思维导图 — 返回 Mermaid 格式代码

    Args:
        title: 导图标题
        data: 结构化数据，格式为 {"root": {"children": [{"name": "节点", "children": []}]}}
        output_format: 输出格式，目前仅支持 "mermaid"

    Returns:
        {success, format, code, title, error}
    """
    if output_format.lower() != "mermaid":
        return {"success": False, "code": None,
                "error": f"不支持的格式: {output_format}，仅支持 mermaid"}

    try:
        mermaid_lines = [f"mindmap\n  root(( {title} ))"]

        def add_node(parent_indent: str, node: Dict, index: int = 0):
            name = node.get("name", f"node_{index}")
            children = node.get("children", [])

            indent = "  " * (parent_indent.count("  ") + 1)
            mermaid_lines.append(f"{indent}{name}")

            for i, child in enumerate(children):
                add_node(indent, child, i)

        root_node = data.get("root", data)
        if isinstance(root_node, dict):
            children = root_node.get("children", [])
            for i, child in enumerate(children):
                add_node("  ", child, i)

        return {
            "success": True,
            "format": "mermaid",
            "code": "\n".join(mermaid_lines),
            "title": title,
            "error": None
        }
    except Exception as e:
        return {"success": False, "code": None, "title": title, "error": str(e)}


def generate_mindmap_from_tree(title: str, tree: Dict[str, Any],
                               output_format: str = "mermaid") -> Dict[str, Any]:
    """
    从树形结构生成思维导图

    是 generate_mindmap 的便捷包装，自动将 tree 包装为 root。

    Args:
        title: 导图标题
        tree: 树形结构 {"name": "根", "children": [...]}
        output_format: 输出格式

    Returns:
        {success, format, code, title, error}
    """
    data = {"root": tree}
    return generate_mindmap(title, data, output_format)


def list_mindmaps() -> Dict[str, Any]:
    """
    列出内置思维导图模板

    Returns:
        {success, templates, count, note, error}
    """
    templates = [
        {"id": "project_structure", "name": "项目结构",
         "description": "展示目录结构和模块关系"},
        {"id": "knowledge_graph", "name": "知识图谱",
         "description": "组织概念和关联"},
        {"id": "decision_tree", "name": "决策树",
         "description": "可视化决策流程"},
        {"id": "workflow", "name": "工作流",
         "description": "展示步骤和依赖关系"},
    ]

    return {
        "success": True,
        "templates": templates,
        "count": len(templates),
        "note": "静态模板列表，实际导图通过 generate_mindmap 动态生成",
        "error": None
    }
