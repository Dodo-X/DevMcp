# data_governance 归一化模块
#
# v9.11: 统一管理 domain/task_type/system_id 的归一化映射，
# 确保知识提取和对话管理的口径一致，避免同义词漂移污染分析层。

import logging

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 归一化映射表
# ══════════════════════════════════════════════════════════

DOMAIN_CANONICAL = {
    # Python 同义词
    "Python编程": "Python",
    "Python 编程": "Python",
    "python": "Python",
}

TASK_TYPE_CANONICAL = {
    "debugging": "debug",
    "coding": "code_change",
}

SYSTEM_ID_CANONICAL = {
    "devpartner": "devPartner",
}

# 标准 domain 白名单 — 不在名单内的标记为"通用工程"
_STANDARD_DOMAINS = frozenset({
    "Python", "前端", "AI/LLM", "DevOps", "数据库", "架构设计", "通用工程",
})


def normalize_domain(raw: str) -> str:
    """将 domain 归一化为标准值。

    策略：
    1. 精确匹配标准化映射表
    2. 前缀匹配（如"数据库设计"→"数据库"）
    3. 不在标准白名单的归入"通用工程"
    """
    if not raw:
        return "通用工程"

    # 精确匹配
    canonical = DOMAIN_CANONICAL.get(raw)
    if canonical:
        return canonical

    # 白名单命中则直接返回
    if raw in _STANDARD_DOMAINS:
        return raw

    # 前缀匹配：尝试找出包含标准域名的变体
    for std in _STANDARD_DOMAINS:
        if std in raw:
            logger.debug(f"domain 前缀归一: {raw!r} → {std!r}")
            return std

    # 兜底
    logger.debug(f"domain 无法归一，归入通用工程: {raw!r}")
    return "通用工程"


def normalize_task_type(raw: str) -> str:
    """将 task_type 归一化为标准值。"""
    if not raw:
        return "general"
    return TASK_TYPE_CANONICAL.get(raw, raw)


def normalize_system_id(raw: str) -> str:
    """将 system_id 归一化为标准大小写。"""
    if not raw:
        return "default"
    return SYSTEM_ID_CANONICAL.get(raw, raw)


def fix_existing_data(db) -> dict:
    """修复存量数据的归一化问题。

    在数据库初始化后、分析服务启动前调用一次。
    对所有表执行 UPDATE，统一口径。

    Args:
        db: DatabaseManager 实例（需支持 query_local）

    Returns:
        dict: {table: rows_updated}
    """
    results = {}

    # ── knowledge_points.domain ──
    # 搜集所有非标准 domain
    rows = db.query_local("SELECT DISTINCT domain FROM knowledge_points")
    domain_fixes = 0
    for row in rows:
        raw = row["domain"]
        canonical = normalize_domain(raw)
        if canonical != raw:
            db.query_local(
                "UPDATE knowledge_points SET domain = ? WHERE domain = ?",
                (canonical, raw),
            )
            domain_fixes += 1
            logger.info(f"domain 归一: {raw!r} → {canonical!r}")
    results["knowledge_points.domain"] = domain_fixes

    # ── conversations.task_type ──
    task_fixes = 0
    for raw, canonical in TASK_TYPE_CANONICAL.items():
        result = db.query_local(
            "UPDATE conversations SET task_type = ? WHERE task_type = ?",
            (canonical, raw),
        )
        affected = result[0].get("affected_rows", 0) if result else 0
        if affected > 0:
            task_fixes += affected
            logger.info(f"task_type 归一: {raw!r} → {canonical!r} ({affected} 行)")
    results["conversations.task_type"] = task_fixes

    # ── conversations.system_id ──
    sys_fixes = 0
    for raw, canonical in SYSTEM_ID_CANONICAL.items():
        result = db.query_local(
            "UPDATE conversations SET system_id = ? WHERE system_id = ?",
            (canonical, raw),
        )
        affected = result[0].get("affected_rows", 0) if result else 0
        if affected > 0:
            sys_fixes += affected
            logger.info(f"system_id 归一: {raw!r} → {canonical!r} ({affected} 行)")
    results["conversations.system_id"] = sys_fixes

    return results


def fix_orphan_steps(db) -> dict:
    """隔离孤儿步骤 — 删除无法关联到 conversation 的步骤。

    Args:
        db: DatabaseManager 实例

    Returns:
        dict: {orphaned_count: int, step_ids: list}
    """
    orphans = db.query_local("""
        SELECT cs.id, cs.step_id
        FROM conversation_steps cs
        LEFT JOIN conversations c ON cs.conversation_id = c.conversation_id
        WHERE c.conversation_id IS NULL
    """)
    ids = [row["step_id"] for row in orphans]  # step_id
    count = len(ids)

    if count > 0:
        placeholders = ",".join("?" for _ in ids)
        db.query_local(
            f"DELETE FROM conversation_steps WHERE step_id IN ({placeholders})",
            ids,
        )
        logger.warning(f"隔离 {count} 个孤儿步骤: {ids}")

    return {"orphaned_count": count, "step_ids": ids}
