"""
统一知识提取器 v2.1
===================

在 conversation_finalize 阶段，通过 LLM 同时从对话中提取：
- 技能知识点（通用编程技巧、框架用法等）
- 业务知识点（项目级业务规则、决策、配置等）
- 分析新知识与已有知识库的关联

核心改进：
- ★ 统一 Prompt：一次 LLM 调用同时提取技能 + 业务知识
- ★ 关联分析：LLM 分析新知识与已有标题的关联
- ★ 去重逻辑：按 title + type + domain 判断
- ★ 使用 type 字段区分 skill/business（非 category）
- v9.5.7: 移除 source_session_id / source_step_id 无用字段
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeExtractor:
    """统一知识提取器（v2.0）"""

    def __init__(self):
        self._db = None

    @property
    def db(self):
        if self._db is None:
            from backend.core.database.base_conn import get_db

            self._db = get_db()
        return self._db

    # ══════════════════════════════════════════════════════════
    # 公开方法
    # ══════════════════════════════════════════════════════════

    def extract_all(
        self, conversation_id: str, conversation_text: str = "", key_decisions: list = None
    ) -> dict[str, Any]:
        """
        统一提取技能 + 业务知识（v9.5.7 精简参数）。

        Args:
            conversation_id: 对话 ID
            conversation_text: 完整对话文本
            key_decisions: 关键决策列表（LLM 不可用时的降级方案）

        Returns:
            {
                "skill_extracted": int,
                "business_extracted": int,
                "knowledge_ids": [str],
                "llm_used": bool,
            }
        """
        result = {
            "skill_extracted": 0,
            "business_extracted": 0,
            "knowledge_ids": [],
            "llm_used": False,
        }

        project_name = self._derive_project_name()

        # 尝试 LLM 统一提取
        try:
            from backend.core.llm_kernel.base_client import get_llm_engine

            llm = get_llm_engine()
            if llm and llm.is_available() and conversation_text:
                result["llm_used"] = True

                existing_titles = self._get_all_titles()

                from backend.templates.llm_prompt import TASK_KNOWLEDGE_EXTRACTION, run_analysis

                parsed = run_analysis(
                    TASK_KNOWLEDGE_EXTRACTION,
                    project_name=project_name,
                    existing_titles_list="\n".join(f"- {t}" for t in existing_titles)
                    if existing_titles
                    else "（暂无已有知识）",
                    conversation_text=conversation_text,
                )
                if parsed and isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        kp_id = self._save_knowledge(
                            item=item,
                            conversation_id=conversation_id,
                            project_name=project_name,
                        )
                        if kp_id:
                            result["knowledge_ids"].append(kp_id)
                            kp_type = item.get("type", "skill")
                            if kp_type == "business":
                                result["business_extracted"] += 1
                            else:
                                result["skill_extracted"] += 1

                    logger.info(
                        f"📚 知识提取: 技能={result['skill_extracted']}条, "
                        f"业务={result['business_extracted']}条 "
                        f"（项目: {project_name}，对话: {conversation_id}）"
                    )
        except Exception as e:
            logger.warning(f"知识提取 LLM 调用失败（非致命）: {e}")

        # 降级：从 key_decisions 中提取基础业务知识
        if result["business_extracted"] == 0 and key_decisions:
            try:
                for decision in key_decisions:
                    d = decision.get("decision", "")
                    r = decision.get("reason", "")
                    if not d:
                        continue
                    item = {
                        "type": "business",
                        "domain": project_name,
                        "title": d[:100],
                        "content": f"决策: {d}\n原因: {r or '未记录'}\n权衡: {decision.get('tradeoff', '未记录')}",
                        "category": "decision",
                        "tags": ["decision", "from_finalize"],
                        "difficulty": "medium",
                        "aliases": [],
                        "related_titles": [],
                    }
                    kp_id = self._save_knowledge(
                        item=item,
                        conversation_id=conversation_id,
                        project_name=project_name,
                    )
                    if kp_id:
                        result["knowledge_ids"].append(kp_id)
                        result["business_extracted"] += 1
            except Exception as e:
                logger.warning(f"业务知识降级提取失败: {e}")

        return result

    def get_all_titles(self) -> list[str]:
        """获取所有已有知识标题列表"""
        return self._get_all_titles()

    # ══════════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════════

    def _get_all_titles(self) -> list[str]:
        """从 knowledge_points 查询所有已有标题"""
        try:
            rows = self.db.query_local("SELECT title FROM knowledge_points ORDER BY id")
            return [row["title"] for row in (rows or [])]
        except Exception:
            return []

    def _save_knowledge(self, item: dict, conversation_id: str, project_name: str) -> str | None:
        """
        保存知识点到 knowledge_points 表（v9.5.7 精简参数）。

        去重逻辑：按 title + type + domain 判重
        - 若存在：比较新旧 content，不同则更新并返回已有 ID
        - 若不存在：插入新记录
        """
        title = item.get("title", "").strip()
        content = item.get("content", "").strip()
        if not title or not content:
            return None

        kp_type = item.get("type", "skill")
        domain = item.get("domain", project_name or "General")

        # v9.3.1: 技能类知识点 domain 强制标准化（LLM 可能不遵守 Prompt 归类规则）
        if kp_type == "skill":
            from backend.core.skill_domain_standard import is_standard_domain, normalize_domain

            if not is_standard_domain(domain):
                domain = normalize_domain(domain)

        category = item.get("category", "concept")
        tags = item.get("tags", [])
        difficulty = item.get("difficulty", "medium")
        aliases = item.get("aliases", [])
        related_titles = item.get("related_titles", [])

        # 解析关联标题 → related_ids
        related_ids = self._resolve_related_ids(related_titles)

        try:
            from backend.core.database.base_conn import get_db

            db = get_db()

            # ── 去重检查（title + type + domain）──
            existing = self.db.query_local(
                """SELECT knowledge_id, content, id
                   FROM knowledge_points
                   WHERE title = ? AND type = ? AND domain = ? LIMIT 1""",
                (title, kp_type, domain),
            )

            if existing:
                existing_row = existing[0]
                existing_id = existing_row["knowledge_id"]
                existing_content = existing_row.get("content", "")

                # 内容不同 → 更新
                if content != existing_content:
                    self.db.query_local(
                        """UPDATE knowledge_points SET
                               content = ?, tags = ?, aliases = ?,
                               difficulty = ?, category = ?,
                               related_knowledge_ids = ?,
                               usage_count = usage_count + 1
                           WHERE knowledge_id = ?""",
                        (
                            content,
                            json.dumps(tags, ensure_ascii=False),
                            json.dumps(aliases, ensure_ascii=False),
                            difficulty,
                            category,
                            json.dumps(related_ids, ensure_ascii=False) if related_ids else "",
                            existing_id,
                        ),
                    )
                    logger.debug(f"🔄 更新已有知识: {title} ({kp_type})")
                else:
                    # 内容相同 → 仅递增 usage_count
                    self.db.query_local(
                        """UPDATE knowledge_points SET
                               usage_count = usage_count + 1
                           WHERE knowledge_id = ?""",
                        (existing_id,),
                    )

                return existing_id

            # ── 新记录 ──
            kp_id = db.insert_knowledge_point(
                title=title,
                content=content,
                category=category,
                domain=domain,
                tags=tags,
                source_id=conversation_id,
                kp_type=kp_type,
                aliases=aliases,
            )

            if kp_id:
                # 更新 difficulty 和 related_knowledge_ids（INSERT 中不包含的字段）
                try:
                    self.db.query_local(
                        """UPDATE knowledge_points SET
                               difficulty = ?, related_knowledge_ids = ?
                           WHERE knowledge_id = ?""",
                        (
                            difficulty,
                            json.dumps(related_ids, ensure_ascii=False) if related_ids else "",
                            kp_id,
                        ),
                    )
                except Exception:
                    pass
                logger.info(f"💡 创建知识: {title} ({kp_type}) → {kp_id}")

            return kp_id

        except Exception as e:
            logger.error(f"保存知识失败 [{title}]: {e}")
            return None

    def _resolve_related_ids(self, related_titles: list[str]) -> list[str]:
        """根据标题列表查找对应的 knowledge_id"""
        if not related_titles:
            return []
        ids = []
        for title in related_titles:
            try:
                row = self.db.query_local(
                    "SELECT knowledge_id FROM knowledge_points WHERE title = ? LIMIT 1", (title,)
                )
                if row:
                    ids.append(row[0]["knowledge_id"])
            except Exception:
                pass
        return ids

    @staticmethod
    def _derive_project_name() -> str:
        """从工作目录名推导项目名"""
        import os

        return os.path.basename(os.getcwd())

    @staticmethod
    def _parse_json(raw: str) -> Any | None:
        """从 LLM 输出中解析 JSON"""
        import re

        if not raw:
            return None
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        json_str = m.group(1) if m else raw
        json_str = json_str.strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            try:
                json_str = re.sub(r",\s*}", "}", json_str)
                json_str = re.sub(r",\s*]", "]", json_str)
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"无法解析 LLM JSON: {json_str[:200]}")
                return None


def get_knowledge_extractor() -> KnowledgeExtractor:
    """获取知识提取器单例"""
    return KnowledgeExtractor()
