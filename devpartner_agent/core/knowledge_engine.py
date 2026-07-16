"""
知识引擎 (v8.0)
================
知识点的统一业务入口。

职责：
  - list_points: 列出知识点
  - search: 搜索知识库
  - create_point: 创建知识点
  - get_point: 获取单个知识点详情

v8.0 变更：
  - 移除内存知识图谱（knowledge_graph.py 已删除）
  - 知识关联由 Obsidian 原生图谱 + [[wikilink]] 承载
  - 知识点提取时由 knowledge_extractor 自动设置 related_knowledge_ids
  - vault_exporter 读取 related_knowledge_ids 生成 [[wikilink]]
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class KnowledgeEngine:
    """知识域业务逻辑"""

    def list_points(self, domain: str = "", category: str = "",
                    limit: int = 50, offset: int = 0) -> dict:
        db = self._get_db()
        conditions = []
        params = []
        if domain:
            conditions.append("domain = ?")
            params.append(domain)
        if category:
            conditions.append("category = ?")
            params.append(category)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM knowledge_points {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = db.query_local(sql, tuple(params))

        count_sql = f"SELECT COUNT(*) as total FROM knowledge_points {where}"
        total = db.query_local(count_sql, tuple(params[:-2]))[0]["total"]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(r) for r in rows],
        }

    def search(self, query: str, domain: str = "", limit: int = 20) -> dict:
        db = self._get_db()
        params = [f"%{query}%", f"%{query}%"]
        domain_filter = ""
        if domain:
            domain_filter = "AND domain = ?"
            params.append(domain)

        sql = f"""
            SELECT * FROM knowledge_points
            WHERE (title LIKE ? OR content LIKE ?) {domain_filter}
            ORDER BY confidence DESC, usage_count DESC
            LIMIT ?
        """
        params.append(limit)
        rows = db.query_local(sql, tuple(params))
        return {
            "query": query,
            "results": len(rows),
            "items": [dict(r) for r in rows],
        }

    def create_point(self, title: str, content: str, domain: str,
                     category: str = "concept", tags_json: str = "[]",
                     difficulty: str = "medium", confidence: float = 0.8) -> dict:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        engine = get_conversation_engine()

        tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
        kp_id = engine.create_knowledge_point(
            title=title, content=content, category=category,
            domain=domain, tags=tags, source_type="manual",
        )

        if kp_id:
            db = self._get_db()
            db.query_local(
                "UPDATE knowledge_points SET confidence = ?, difficulty = ? WHERE knowledge_id = ?",
                (confidence, difficulty, kp_id),
            )

        return {
            "success": bool(kp_id),
            "knowledge_id": kp_id,
            "title": title,
            "domain": domain,
        }

    def get_point(self, knowledge_id: str) -> dict:
        db = self._get_db()
        rows = db.query_local(
            "SELECT * FROM knowledge_points WHERE knowledge_id = ?",
            (knowledge_id,)
        )
        if not rows:
            return {"error": f"知识点 {knowledge_id} 不存在"}
        return dict(rows[0])

    def _get_db(self):
        from devpartner_agent.core.database import get_db
        return get_db()


_instance: Optional[KnowledgeEngine] = None

def get_knowledge_engine() -> KnowledgeEngine:
    global _instance
    if _instance is None:
        _instance = KnowledgeEngine()
    return _instance


def register_knowledge_tools(mcp):
    """注册知识域的所有 MCP 工具"""

    @mcp.tool()
    def list_knowledge_points(domain: str = "", category: str = "",
                              limit: int = 50, offset: int = 0) -> str:
        """获取知识库中的知识点列表，支持按领域和分类过滤。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_knowledge_engine()
            return engine.list_points(domain, category, limit, offset)
        return _inner()

    @mcp.tool()
    def search_knowledge(query: str, domain: str = "", limit: int = 20) -> str:
        """搜索知识库中的知识点。支持在标题、内容和标签中模糊搜索。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_knowledge_engine()
            return engine.search(query, domain, limit)
        return _inner()

    @mcp.tool()
    def create_knowledge_point(title: str, content: str, domain: str,
                               category: str = "concept", tags_json: str = "[]",
                               difficulty: str = "medium", confidence: float = 0.8) -> str:
        """手动创建知识点。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_knowledge_engine()
            return engine.create_point(title, content, domain, category, tags_json, difficulty, confidence)
        return _inner()

    @mcp.tool()
    def get_knowledge_point(knowledge_id: str) -> str:
        """获取单个知识点的详细信息。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_knowledge_engine()
            return engine.get_point(knowledge_id)
        return _inner()