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

logger = logging.getLogger(__name__)


class KnowledgeEngine:
    """知识域业务逻辑"""

    def list_points(
        self, domain: str = "", category: str = "", limit: int = 50, offset: int = 0
    ) -> dict:
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

    def create_point(
        self,
        title: str,
        content: str,
        domain: str,
        category: str = "concept",
        tags_json: str = "[]",
        difficulty: str = "medium",
        confidence: float = 0.8,
    ) -> dict:
        from backend.business.conversation_mgr import get_conversation_engine

        engine = get_conversation_engine()

        tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
        kp_id = engine.create_knowledge_point(
            title=title,
            content=content,
            category=category,
            domain=domain,
            tags=tags,
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
            "SELECT * FROM knowledge_points WHERE knowledge_id = ?", (knowledge_id,)
        )
        if not rows:
            return {"error": f"知识点 {knowledge_id} 不存在"}

        # v9.11: 访问计数递增
        self._increment_usage(knowledge_id)
        return dict(rows[0])

    def match_knowledge(self, query: str, limit: int = 20) -> dict:
        """AI 智能匹配知识点：先用 LLM 分析问题领域，再搜索对应知识点。

        两阶段流程：
        1. LLM 分析 query → 提取 matched_domain + match_reason
        2. 在 matched_domain 下搜索相关知识 + 全库关键词搜索兜底
        """
        import json as _json

        db = self._get_db()

        # ── 阶段一：LLM 分析问题领域 ──
        matched_domain = ""
        match_reason = ""
        try:
            from backend.core.llm_kernel.base_client import get_llm_engine

            llm = get_llm_engine()
            prompt = _json.dumps(
                {
                    "task": "analyze_question_domain",
                    "question": query,
                    "instruction": (
                        "你是一个技术领域分类器。分析以下问题，返回JSON格式：\n"
                        '{"domain": "最匹配的技术领域（如Python/前端/AI/DevOps/数据库/架构设计/通用工程）", '
                        '"reason": "匹配理由（一句话，20字以内）"}\n'
                        "只返回JSON，不要其他内容。"
                    ),
                },
                ensure_ascii=False,
            )
            llm_result = llm.infer(prompt, timeout=15)
            if llm_result and llm_result.strip():
                # 提取 JSON
                json_start = llm_result.find("{")
                json_end = llm_result.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    parsed = _json.loads(llm_result[json_start:json_end])
                    matched_domain = (parsed.get("domain") or "").strip()
                    match_reason = (parsed.get("reason") or "").strip()
        except Exception as e:
            logger.warning(f"LLM 领域匹配失败，回退到全库搜索: {e}")

        # ── 阶段二：搜索知识点 ──
        items = []
        if matched_domain:
            # 先按匹配的领域搜索
            domain_rows = db.query_local(
                "SELECT * FROM knowledge_points WHERE domain = ? ORDER BY usage_count DESC LIMIT ?",
                (matched_domain, limit),
            )
            for r in domain_rows or []:
                content = r.get("content", "")
                items.append(
                    {
                        "knowledge_id": r.get("knowledge_id", ""),
                        "title": r.get("title", ""),
                        "summary": content[:200] + "..." if len(content) > 200 else content,
                        "domain": r.get("domain", ""),
                        "category": r.get("category", ""),
                        "difficulty": r.get("difficulty", "medium"),
                        "usage_count": r.get("usage_count", 0),
                        "confidence": r.get("confidence", 0),
                        "created_at": r.get("created_at", ""),
                    }
                )

        # 关键词搜索兜底（补充或填充）
        if len(items) < limit:
            search_rows = db.query_local(
                "SELECT * FROM knowledge_points WHERE "
                "(title LIKE ? OR content LIKE ?) "
                + (
                    "AND knowledge_id NOT IN ({}) ".format(",".join("?" * len(items)))
                    if items
                    else ""
                )
                + "ORDER BY usage_count DESC LIMIT ?",
                tuple(
                    [f"%{query}%", f"%{query}%"]
                    + ([it["knowledge_id"] for it in items] if items else [])
                    + [limit - len(items)]
                ),
            )
            for r in search_rows or []:
                content = r.get("content", "")
                items.append(
                    {
                        "knowledge_id": r.get("knowledge_id", ""),
                        "title": r.get("title", ""),
                        "summary": content[:200] + "..." if len(content) > 200 else content,
                        "domain": r.get("domain", ""),
                        "category": r.get("category", ""),
                        "difficulty": r.get("difficulty", "medium"),
                        "usage_count": r.get("usage_count", 0),
                        "confidence": r.get("confidence", 0),
                        "created_at": r.get("created_at", ""),
                    }
                )

        # v9.11: 批量递增匹配的知识点访问计数
        matched_ids = [it["knowledge_id"] for it in items]
        if matched_ids:
            try:
                placeholders = ",".join("?" for _ in matched_ids)
                db.query_local(
                    f"UPDATE knowledge_points SET usage_count = usage_count + 1 WHERE knowledge_id IN ({placeholders})",
                    tuple(matched_ids),
                )
            except Exception:
                pass  # 非关键操作

        return {
            "success": True,
            "query": query,
            "matched_domain": matched_domain,
            "match_reason": match_reason,
            "count": len(items),
            "items": items,
        }

    def _increment_usage(self, knowledge_id: str):
        """v9.11: 记录知识点被访问（usage_count += 1）"""
        try:
            db = self._get_db()
            db.query_local(
                "UPDATE knowledge_points SET usage_count = usage_count + 1 WHERE knowledge_id = ?",
                (knowledge_id,),
            )
        except Exception:
            pass  # 非关键操作，静默降级

    def _get_db(self):
        from backend.core.database.base_conn import get_db

        return get_db()


_instance: KnowledgeEngine | None = None


def get_knowledge_engine() -> KnowledgeEngine:
    global _instance
    if _instance is None:
        _instance = KnowledgeEngine()
    return _instance
