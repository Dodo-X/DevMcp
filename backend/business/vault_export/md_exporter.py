"""
MD 导出工具 v1.0 — 统一 MD 文档导出入口
========================================

v9.8.4: 从 conversation_engine.py 的 handle 方法中提取 MD 导出逻辑，
       所有 MD 导出统一走此模块，不再在业务代码中直接拼接模板或操作文件。

设计原则：
  - conversation_engine 只做 DB + 调用 LLM + 调用本模块
  - 本模块负责：取数据 → 装配 MD 模板 → 写入文件
  - 所有 MD 模板定义在 md_templates.py，通过 MdAssembler 装配
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class MdExporter:
    """统一 MD 导出器 — 将 DB 数据装配到 MD 模板并写入文件。"""

    def __init__(self):
        self._assembler = None

    @property
    def assembler(self):
        if self._assembler is None:
            from backend.business.vault_export.md_engine import get_assembler
            from backend.business.vault_export.md_templates import register_all

            self._assembler = get_assembler()
            register_all(self._assembler)
        return self._assembler

    def _get_db(self):
        from backend.core.database.base_conn import get_db

        return get_db()

    # ══════════════════════════════════════════════════════════
    # 对话知识摘要 MD（原 handle_finalize_knowledge_graph）
    # ══════════════════════════════════════════════════════════

    def export_knowledge_summary(
        self, conversation_id: str, topic: str = "", system_id: str = "default", on_progress=None
    ) -> dict:
        """
        从 knowledge_points 表读取本对话的所有知识点，
        装配为知识摘要 MD 并导出到 Efforts/{system}/知识摘要/{conv_id}.md。

        v9.9.2 修复: source_id 存的可能是 step_id（step_analysis 写入时）或
        conversation_id（finalize 知识提取时），需要通过 conversation_steps 关联查询。
        返回值增加 knowledge_ids 字段，供下游知识卡片导出使用。

        Returns: {"success": bool, "md_path": str|None, "kp_count": int, "knowledge_ids": [str]}
        """
        db = self._get_db()
        result = {"success": False, "md_path": None, "kp_count": 0, "knowledge_ids": []}

        try:
            # ── 读取知识点（v9.9.2: 支持 source_id=step_id 和 source_id=conversation_id 两种）──
            try:
                # 先查该 conversation 的所有 step_id
                step_rows = db.query_local(
                    "SELECT step_id FROM conversation_steps WHERE conversation_id = ?",
                    (conversation_id,),
                )
                step_ids = [s["step_id"] for s in (step_rows or []) if s.get("step_id")]

                # source_id 可能是 step_id 或 conversation_id，用 IN 兼容两种
                source_ids = step_ids + [conversation_id]
                placeholders = ",".join("?" for _ in source_ids)
                kp_rows = db.query_local(
                    f"SELECT knowledge_id, title, content, category, domain, tags, "
                    f"created_at FROM knowledge_points WHERE source_id IN ({placeholders}) "
                    f"ORDER BY created_at",
                    tuple(source_ids),
                )
            except Exception:
                kp_rows = []

            if not kp_rows:
                result["success"] = True
                return result

            result["kp_count"] = len(kp_rows)
            result["knowledge_ids"] = [row["knowledge_id"] for row in kp_rows]

            # ── 规范化知识点数据 ──
            domains = {}
            for row in kp_rows:
                domain = row.get("domain", "General") or "General"
                if domain not in domains:
                    domains[domain] = []
                tags_raw = row.get("tags", "")
                if isinstance(tags_raw, str):
                    try:
                        tags = json.loads(tags_raw)
                    except Exception:
                        tags = [tags_raw] if tags_raw else []
                elif isinstance(tags_raw, list):
                    tags = tags_raw
                else:
                    tags = []
                domains[domain].append(
                    {
                        "title": row.get("title", "") or "未命名",
                        "content": (row.get("content", "") or "")[:3000],
                        "category": row.get("category", "skill") or "skill",
                        "tags": tags,
                    }
                )

            # ── 组装 MD 内容 ──
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lines = [
                f"# 对话知识摘要: {topic or '未命名对话'}",
                "",
                f"- **对话 ID**: `{conversation_id}`",
                f"- **系统**: {system_id}",
                f"- **生成时间**: {now_str}",
                f"- **知识点总数**: {len(kp_rows)}",
                "",
                "---",
                "",
            ]

            for domain, items in sorted(domains.items()):
                lines.append(f"## {domain}")
                lines.append("")
                for item in items:
                    lines.append(f"### {item['title']}")
                    lines.append(f"- **类型**: {item['category']} | **领域**: {domain}")
                    tags_str = " ".join(f"`{t}`" for t in item["tags"]) if item["tags"] else ""
                    if tags_str:
                        lines.append(f"- **标签**: {tags_str}")
                    lines.append("")
                    lines.append(item["content"])
                    lines.append("")
                    lines.append("---")
                    lines.append("")

            md_content = "\n".join(lines)

            # ── 写入文件 ──
            vault_root = self.assembler.vault_root
            md_dir = Path(vault_root) / "Efforts" / system_id / "知识摘要"
            md_dir.mkdir(parents=True, exist_ok=True)
            safe_name = conversation_id.replace(":", "_").replace("/", "_")
            md_path = md_dir / f"{safe_name}.md"
            md_path.write_text(md_content, encoding="utf-8")

            result["md_path"] = str(md_path)
            result["success"] = True

            if on_progress:
                on_progress(1.0, "", "知识摘要 MD 生成完成")

            logger.info(
                f"📕 知识摘要 MD 已导出: {conversation_id} | {len(kp_rows)} 个知识点 → {md_path}"
            )

        except Exception as e:
            logger.error(f"知识摘要 MD 导出失败: {e}", exc_info=True)
            result["error"] = str(e)[:500]

        return result

    # ══════════════════════════════════════════════════════════
    # 项目画像 MD（原 handle_finalize_business_tech 中的调用）
    # ══════════════════════════════════════════════════════════

    def export_project_profile(self, system_id: str) -> bool:
        """
        从 connected_systems 表读取项目数据，
        装配为项目画像 MD 并导出到 Efforts/{system}/项目画像.md。
        """
        if system_id == "default":
            return False
        try:
            db = self._get_db()
            proj_row = db.query_local(
                "SELECT * FROM connected_systems WHERE system_id = ?",
                (system_id,),
            )
            if not proj_row:
                return False

            from backend.business.vault_export.vault_exporter import get_vault_exporter

            exporter = get_vault_exporter()
            exporter.export_project_to_vault(system_id, dict(proj_row[0]))
            logger.info(f"📊 项目画像 MD 已导出: {system_id}")
            return True
        except Exception as e:
            logger.warning(f"项目画像 MD 导出失败（非致命）: {e}")
            return False

    # ══════════════════════════════════════════════════════════
    # 用户画像 MD（原 handle_finalize_user_profile 中的调用）
    # ══════════════════════════════════════════════════════════

    def export_user_profile(self, date_str: str = "") -> bool:
        """
        从 user_profile 表读取维度数据，
        装配为用户画像 MD 并导出到 Atlas/用户画像.md。
        """
        try:
            db = self._get_db()
            profile_rows = db.query_local(
                "SELECT dimension, value, confidence, trend, observation_count FROM user_profile"
            )
            profile_data = {}
            for row in profile_rows or []:
                profile_data[row["dimension"]] = {
                    "value": row["value"],
                    "confidence": row["confidence"],
                    "trend": row["trend"],
                    "observation_count": row["observation_count"],
                }
            if not profile_data:
                return False

            from backend.business.vault_export.vault_exporter import get_vault_exporter

            exporter = get_vault_exporter()
            exporter.export_profile_to_vault(
                profile_data, date_str or datetime.now().strftime("%Y-%m-%d")
            )
            logger.info("👤 用户画像 MD 已导出")
            return True
        except Exception as e:
            logger.warning(f"用户画像 MD 导出失败（非致命）: {e}")
            return False

    # ══════════════════════════════════════════════════════════
    # v9.9.3: export_knowledge_cards 已删除。
    # 知识卡片导出统一由 handle_conversation_finalize → vault_export_batch 异步处理，
    # 不再需要同步的重复导出路径。
    # ══════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_exporter: MdExporter | None = None


def get_md_exporter() -> MdExporter:
    global _exporter
    if _exporter is None:
        _exporter = MdExporter()
    return _exporter
