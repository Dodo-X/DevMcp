"""
知识图谱服务 (v5.2)
====================
从 knowledge_points 表自动构建知识点间的关联关系网络。

核心功能：
  - 领域聚类：按 domain 自动分组知识点
  - 标签共现：基于共享 tag 发现关联
  - 来源关联：同一次对话产生的知识点自动关联
  - 相似度计算：基于内容关键词的 Jaccard 相似度
  - 图谱查询：按节点ID获取邻居节点
  - 路径发现：查找两个知识点之间的关联路径

设计原则：
  - 纯内存计算（无需图数据库）
  - 增量更新（只计算变化部分）
  - 懒加载（首次查询时才构建索引）
  - 可缓存（索引构建结果可持久化）

使用示例：
    kg = KnowledgeGraph()
    kg.build_index()  # 构建全量索引
    neighbors = kg.get_neighbors("kp_001")  # 获取相邻节点
    path = kg.find_path("kp_001", "kp_099")  # 查找路径
    cluster = kg.get_cluster("Python")  # 按领域聚类
"""

import json
import logging
import threading
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Set, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    """图节点"""
    knowledge_id: str
    title: str
    domain: str
    category: str
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.8
    usage_count: int = 0
    difficulty: str = "medium"
    version: int = 1


@dataclass
class GraphEdge:
    """图边"""
    source_id: str
    target_id: str
    weight: float
    relation_type: str
    evidence: str = ""


class KnowledgeGraph:
    """
    知识图谱引擎 - 从 knowledge_points 构建关系网络
    """

    def __init__(self):

        self._nodes: Dict[str, GraphNode] = {}
        self._edges: Dict[str, Dict[str, GraphEdge]] = {}
        self._domain_index: Dict[str, List[str]] = defaultdict(list)
        self._tag_index: Dict[str, List[str]] = defaultdict(list)
        self._source_index: Dict[str, List[str]] = defaultdict(list)

        self._index_built = False
        self._last_build_time: Optional[datetime] = None
        self._node_count = 0
        self._edge_count = 0

        logger.info("KnowledgeGraph service initialized")

    # ══════════════════════════════════════════════════════════
    # Index Building
    # ══════════════════════════════════════════════════════════

    def build_index(self, force: bool = False) -> Dict[str, Any]:
        """Build full knowledge graph index from database"""
        if self._index_built and not force:
            return {
                "status": "already_built",
                "nodes": self._node_count,
                "edges": self._edge_count,
                "last_build": self._last_build_time.isoformat() if self._last_build_time else None,
            }

        logger.info("Building knowledge graph index...")
        start_time = datetime.now()

        try:
            from devpartner_agent.core.database import get_db
            db = get_db()

            rows = db.query_local("""
                SELECT knowledge_id, title, content, category, domain, tags,
                       confidence, usage_count, difficulty, version,
                       source_type, source_id, related_knowledge_ids
                FROM knowledge_points
                ORDER BY usage_count DESC
            """)

            if not rows:
                self._index_built = True
                return {"status": "empty", "nodes": 0, "edges": 0}

            # Build nodes
            self._nodes.clear()
            self._domain_index.clear()
            self._tag_index.clear()
            self._source_index.clear()
            self._edges.clear()

            for row in rows:
                kid = row["knowledge_id"]
                tags = self._parse_tags(row.get("tags", "[]"))
                node = GraphNode(
                    knowledge_id=kid,
                    title=row.get("title", "Untitled"),
                    domain=row.get("domain", "General"),
                    category=row.get("category", "general"),
                    tags=tags,
                    confidence=row.get("confidence", 0.8),
                    usage_count=row.get("usage_count", 0),
                    difficulty=row.get("difficulty", "medium"),
                    version=row.get("version", 1),
                )
                self._nodes[kid] = node
                self._domain_index[node.domain].append(kid)
                for tag in tags:
                    self._tag_index[tag].append(kid)
                sid = row.get("source_id")
                if sid:
                    self._source_index[sid].append(kid)

            self._node_count = len(self._nodes)

            # Build edges
            self._build_edges_from_domains()
            self._build_edges_from_tags()
            self._build_edges_from_sources()
            self._build_edges_from_explicit(rows)
            self._build_edges_from_similarity(rows)

            self._edge_count = sum(len(t) for t in self._edges.values())
            self._index_built = True
            self._last_build_time = datetime.now()

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"Knowledge graph built: {self._node_count} nodes, "
                        f"{self._edge_count} edges in {elapsed:.2f}s")

            return {
                "status": "built",
                "nodes": self._node_count,
                "edges": self._edge_count,
                "domains": len(self._domain_index),
                "tags": len(self._tag_index),
                "elapsed_seconds": round(elapsed, 2),
            }

        except Exception as e:
            logger.error(f"Failed to build knowledge graph: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    def _parse_tags(self, tags_raw) -> List[str]:
        """Parse tags from JSON string or list"""
        if isinstance(tags_raw, list):
            return [str(t) for t in tags_raw]
        try:
            return json.loads(tags_raw) if isinstance(tags_raw, str) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _build_edges_from_domains(self):
        """Same domain nodes get weak edges"""
        for domain, kids in self._domain_index.items():
            if len(kids) < 2:
                continue
            sorted_kids = sorted(kids, key=lambda k: self._nodes[k].usage_count, reverse=True)
            hub = sorted_kids[0]
            for kid in sorted_kids[1:]:
                weight = 0.3 + 0.1 * min(len(kids), 10) / 10
                self._add_edge(hub, kid, weight, "shared_domain", f"Domain: {domain}")

    def _build_edges_from_tags(self):
        """Shared tags create edges"""
        for tag, kids in self._tag_index.items():
            if len(kids) < 2:
                continue
            for i in range(len(kids)):
                for j in range(i + 1, len(kids)):
                    ki, kj = kids[i], kids[j]
                    tags_i = set(self._nodes[ki].tags)
                    tags_j = set(self._nodes[kj].tags)
                    shared = len(tags_i & tags_j)
                    total = len(tags_i | tags_j)
                    weight = shared / max(total, 1)
                    if weight >= 0.3:
                        self._add_edge(ki, kj, weight, "shared_tags",
                                       f"Tags: {tag}")

    def _build_edges_from_sources(self):
        """Same source conversation = strong edge"""
        for source_id, kids in self._source_index.items():
            if len(kids) < 2:
                continue
            for i in range(len(kids)):
                for j in range(i + 1, len(kids)):
                    self._add_edge(kids[i], kids[j], 0.8, "same_source",
                                   f"Source: {source_id}")

    def _build_edges_from_explicit(self, rows):
        """Explicit related_knowledge_ids edges"""
        for row in rows:
            kid = row["knowledge_id"]
            related = row.get("related_knowledge_ids")
            if not related:
                continue
            try:
                if isinstance(related, str):
                    rids = [r.strip() for r in related.split(",") if r.strip()]
                else:
                    rids = related
                for rid in rids:
                    if rid in self._nodes and rid != kid:
                        self._add_edge(kid, rid, 0.9, "explicit", "Explicit relation")
            except Exception:
                pass

    def _build_edges_from_similarity(self, rows):
        """Content similarity via Jaccard on keywords"""
        keywords: Dict[str, Set[str]] = {}
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on',
            'at', 'to', 'for', 'of', 'with', 'and', 'or', 'this', 'that',
            'it', 'be', 'has', 'have', 'from', 'by', 'as', 'not', 'but',
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都',
            '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你',
            '会', '着', '没有', '看', '好', '自己', '这', '那', '什么',
        }

        for row in rows:
            kid = row["knowledge_id"]
            text = f"{row.get('title', '')} {row.get('content', '')}".lower()
            words = set(re.findall(r'[\w\u4e00-\u9fff]{2,}', text))
            keywords[kid] = words - stopwords

        for domain, kids in self._domain_index.items():
            if len(kids) < 2:
                continue
            for i in range(len(kids)):
                for j in range(i + 1, len(kids)):
                    ki, kj = kids[i], kids[j]
                    wi, wj = keywords.get(ki, set()), keywords.get(kj, set())
                    if not wi or not wj:
                        continue
                    inter = len(wi & wj)
                    union = len(wi | wj)
                    jaccard = inter / union if union > 0 else 0
                    if jaccard >= 0.15:
                        self._add_edge(ki, kj, jaccard * 0.7, "similar_content",
                                       f"Similarity: {jaccard:.2f}")

    def _add_edge(self, source: str, target: str, weight: float,
                  relation_type: str, evidence: str = ""):
        """Add undirected edge (deduplicated)"""
        if source == target:
            return
        if source > target:
            source, target = target, source
        self._edges.setdefault(source, {})
        existing = self._edges[source].get(target)
        if existing and existing.weight >= weight:
            return
        self._edges[source][target] = GraphEdge(
            source_id=source, target_id=target,
            weight=min(weight, 1.0),
            relation_type=relation_type, evidence=evidence,
        )

    # ══════════════════════════════════════════════════════════
    # Query API
    # ══════════════════════════════════════════════════════════

    def get_node(self, knowledge_id: str) -> Optional[Dict[str, Any]]:
        """Get node details"""
        node = self._nodes.get(knowledge_id)
        if not node:
            return None
        return {
            "knowledge_id": node.knowledge_id,
            "title": node.title,
            "domain": node.domain,
            "category": node.category,
            "tags": node.tags,
            "confidence": node.confidence,
            "usage_count": node.usage_count,
            "difficulty": node.difficulty,
            "version": node.version,
        }

    def get_neighbors(self, knowledge_id: str, max_depth: int = 1,
                      min_weight: float = 0.3) -> Dict[str, Any]:
        """Get neighbors up to max_depth hops away"""
        node = self.get_node(knowledge_id)
        if not node:
            return {"error": f"Node not found: {knowledge_id}"}

        visited = {knowledge_id}
        current_level = {knowledge_id}
        all_neighbors = []

        for depth in range(max_depth):
            next_level = set()
            for kid in current_level:
                nbs = self._get_direct_neighbors(kid, min_weight)
                for nb in nbs:
                    if nb["knowledge_id"] not in visited:
                        visited.add(nb["knowledge_id"])
                        nb["depth"] = depth + 1
                        all_neighbors.append(nb)
                        next_level.add(nb["knowledge_id"])
            current_level = next_level

        return {
            "node": node,
            "neighbors": sorted(all_neighbors, key=lambda x: x["weight"], reverse=True),
            "total_connections": len(all_neighbors),
        }

    def _get_direct_neighbors(self, knowledge_id: str, min_weight: float) -> List[Dict]:
        """Get direct (1-hop) neighbors"""
        neighbors = []
        # Check edges where this node is source
        if knowledge_id in self._edges:
            for target, edge in self._edges[knowledge_id].items():
                if edge.weight >= min_weight:
                    node = self._nodes.get(target)
                    if node:
                        neighbors.append({
                            "knowledge_id": target,
                            "title": node.title,
                            "domain": node.domain,
                            "weight": round(edge.weight, 3),
                            "relation_type": edge.relation_type,
                            "evidence": edge.evidence,
                        })

        # Check edges where this node is target
        for source, targets in self._edges.items():
            if knowledge_id in targets:
                edge = targets[knowledge_id]
                if edge.weight >= min_weight:
                    node = self._nodes.get(source)
                    if node:
                        neighbors.append({
                            "knowledge_id": source,
                            "title": node.title,
                            "domain": node.domain,
                            "weight": round(edge.weight, 3),
                            "relation_type": edge.relation_type,
                            "evidence": edge.evidence,
                        })

        return sorted(neighbors, key=lambda x: x["weight"], reverse=True)

    def find_path(self, source_id: str, target_id: str,
                  max_depth: int = 5) -> Dict[str, Any]:
        """Find shortest path between two knowledge points via BFS"""
        if source_id not in self._nodes:
            return {"error": f"Source node not found: {source_id}"}
        if target_id not in self._nodes:
            return {"error": f"Target node not found: {target_id}"}
        if source_id == target_id:
            return {"path": [source_id], "length": 0, "edges": []}

        # BFS
        queue = deque([(source_id, [source_id], [])])
        visited = {source_id}

        while queue:
            current, path, edge_path = queue.popleft()
            if len(path) > max_depth + 1:
                continue

            neighbors = self._get_direct_neighbors(current, 0.1)
            for nb in neighbors:
                nid = nb["knowledge_id"]
                if nid == target_id:
                    final_edges = edge_path + [{
                        "from": current, "to": nid,
                        "weight": nb["weight"],
                        "relation_type": nb["relation_type"],
                    }]
                    return {
                        "path": path + [nid],
                        "length": len(path),
                        "edges": final_edges,
                    }
                if nid not in visited:
                    visited.add(nid)
                    queue.append((
                        nid,
                        path + [nid],
                        edge_path + [{
                            "from": current, "to": nid,
                            "weight": nb["weight"],
                            "relation_type": nb["relation_type"],
                        }],
                    ))

        return {"error": f"No path found within {max_depth} hops"}

    def get_cluster(self, domain: str = None, tag: str = None,
                    min_nodes: int = 1) -> Dict[str, Any]:
        """Get knowledge cluster by domain or tag"""
        if domain:
            kids = self._domain_index.get(domain, [])
        elif tag:
            kids = self._tag_index.get(tag, [])
        else:
            kids = list(self._nodes.keys())

        if len(kids) < min_nodes:
            return {"cluster": domain or tag, "nodes": [], "edges": [], "size": 0}

        # Collect internal edges
        cluster_edges = []
        kid_set = set(kids)
        for kid in kids:
            for nb in self._get_direct_neighbors(kid, 0.2):
                if nb["knowledge_id"] in kid_set and kid < nb["knowledge_id"]:
                    cluster_edges.append({
                        "source": kid,
                        "target": nb["knowledge_id"],
                        "weight": nb["weight"],
                        "relation_type": nb["relation_type"],
                    })

        cluster_nodes = [
            {"knowledge_id": k, "title": self._nodes[k].title,
             "domain": self._nodes[k].domain, "usage_count": self._nodes[k].usage_count}
            for k in kids
        ]

        return {
            "cluster": domain or tag,
            "nodes": sorted(cluster_nodes, key=lambda x: x["usage_count"], reverse=True),
            "edges": sorted(cluster_edges, key=lambda x: x["weight"], reverse=True),
            "size": len(kids),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics"""
        if not self._index_built:
            return {"status": "not_built"}

        # Degree distribution
        degrees = defaultdict(int)
        for kid in self._nodes:
            nbs = self._get_direct_neighbors(kid, 0.1)
            degrees[len(nbs)] += 1

        # Top hub nodes
        hubs = sorted(
            [(kid, len(self._get_direct_neighbors(kid, 0.1)))
             for kid in self._nodes],
            key=lambda x: x[1], reverse=True
        )[:10]

        return {
            "status": "built",
            "total_nodes": self._node_count,
            "total_edges": self._edge_count,
            "total_domains": len(self._domain_index),
            "total_tags": len(self._tag_index),
            "top_domains": sorted(
                [(d, len(ks)) for d, ks in self._domain_index.items()],
                key=lambda x: x[1], reverse=True
            )[:10],
            "top_hubs": [
                {"knowledge_id": kid, "title": self._nodes[kid].title,
                 "connections": deg}
                for kid, deg in hubs
            ],
            "last_built": self._last_build_time.isoformat() if self._last_build_time else None,
        }

    def export_graph(self, format: str = "nodes_and_edges") -> Dict[str, Any]:
        """Export graph data for visualization"""
        if not self._index_built:
            return {"error": "Index not built"}

        if format == "nodes_and_edges":
            return {
                "nodes": [
                    {"id": n.knowledge_id, "label": n.title,
                     "domain": n.domain, "group": n.domain,
                     "value": n.usage_count + 1}
                    for n in self._nodes.values()
                ],
                "edges": [
                    {"from": s, "to": t, "value": round(e.weight, 3),
                     "title": e.relation_type}
                    for s, targets in self._edges.items()
                    for t, e in targets.items()
                ],
            }
        elif format == "adjacency":
            adj = {}
            for kid in self._nodes:
                nbs = self._get_direct_neighbors(kid, 0.3)
                adj[kid] = {nb["knowledge_id"]: nb["weight"] for nb in nbs}
            return {"adjacency": adj}

        return {"error": f"Unknown format: {format}"}

    def sync_relations_to_db(self, min_weight: float = 0.5) -> Dict[str, Any]:
        """
        v7.2: 将图谱中发现的共现关系写回 knowledge_points.related_knowledge_ids。
        
        基于现有边的权重筛选高质量关联（≥ min_weight），
        去重后以逗号分隔的 knowledge_id 列表写入 DB。
        
        只更新已变更的记录，减少不必要的写操作。
        """
        if not self._index_built:
            return {"status": "not_built", "message": "请先 build_index() 构建图谱"}

        try:
            from devpartner_agent.core.database import get_db
            db = get_db()

            # 收集每个节点的关联邻居
            relations: Dict[str, List[str]] = defaultdict(list)
            for source, targets in self._edges.items():
                for target, edge in targets.items():
                    if edge.weight >= min_weight:
                        relations[source].append(target)
                        relations[target].append(source)

            updated = 0
            skipped = 0
            for kid, related_ids in relations.items():
                # 去重 + 排序（保持确定性）
                unique_related = sorted(set(related_ids))
                new_related_str = ",".join(unique_related)

                # 读取当前值，避免不必要的 UPDATE
                current = db.query_local(
                    "SELECT related_knowledge_ids FROM knowledge_points WHERE knowledge_id = ?",
                    (kid,)
                )
                if current and current[0].get("related_knowledge_ids") == new_related_str:
                    skipped += 1
                    continue

                db.query_local(
                    "UPDATE knowledge_points SET related_knowledge_ids = ?, updated_at = ? WHERE knowledge_id = ?",
                    (new_related_str, datetime.now().isoformat(), kid)
                )
                updated += 1

            return {
                "status": "success",
                "nodes_processed": len(self._nodes),
                "nodes_with_relations": len(relations),
                "updated": updated,
                "skipped": skipped,
                "min_weight": min_weight,
            }

        except Exception as e:
            logger.error(f"sync_relations_to_db failed: {e}")
            return {"status": "error", "error": str(e)}


# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
_knowledge_graph_instance: Optional[KnowledgeGraph] = None

def get_knowledge_graph() -> KnowledgeGraph:
    """Get global KnowledgeGraph singleton"""
    global _knowledge_graph_instance
    if _knowledge_graph_instance is None:
        _knowledge_graph_instance = KnowledgeGraph()
    return _knowledge_graph_instance
