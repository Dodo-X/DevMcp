"""
AI配置优化建议服务
==================
分析调用者（CodeBuddy/Trae/Cursor 等）的配置，给出改进建议。

原则：
  - 只分析，不直接修改AI客户端配置
  - 通过模块协作消息或日志给出建议
  - 检测配置问题并提出解决方案

分析维度：
  1. MCP 配置完整性（是否连接了 devPartner）
  2. Rules/Skills 覆盖度
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from devpartner_agent.core import KNOWN_CLIENTS


class AIOptimizer:
    """
    AI 配置分析器
    
    分析 CodeBuddy/Trae 等AI客户端的配置，提出优化建议。
    """

    def __init__(self):
        self.analyses: List[dict] = []
        self.pending_suggestions: List[dict] = []

    def analyze_client(self, client_name: str, workspace_root: str) -> dict:
        """
        全面分析一个 AI 客户端配置
        
        返回：{status, issues, suggestions, score}
        """
        ws = Path(workspace_root)
        client_info = KNOWN_CLIENTS.get(client_name.lower(), {})
        config_dir_name = client_info.get("config_dir", ".unknown")
        config_dir = ws / config_dir_name

        analysis = {
            "client": client_name,
            "workspace": str(ws),
            "config_dir": str(config_dir),
            "config_dir_exists": config_dir.exists(),
            "timestamp": datetime.now().isoformat(),
            "issues": [],
            "suggestions": [],
            "score": 100,  # 满分100，发现问题扣分
        }

        if not config_dir.exists():
            analysis["issues"].append({
                "severity": "warning",
                "category": "config_missing",
                "message": f"未找到 {config_dir_name}/ 配置目录",
            })
            analysis["score"] -= 20
            return analysis

        # 检查 1: MCP 配置
        mcp_issues = self._check_mcp_config(ws, config_dir_name, client_name)
        analysis["issues"].extend(mcp_issues)
        analysis["score"] -= len(mcp_issues) * 10

        # 检查 2: Rules 配置
        rule_issues = self._check_rules(config_dir)
        analysis["issues"].extend(rule_issues)
        analysis["score"] -= len(rule_issues) * 5

        # 生成建议
        analysis["suggestions"] = self._generate_suggestions(
            analysis["issues"], client_name, workspace_root
        )

        # 计算评分
        analysis["score"] = max(0, analysis["score"])

        self.analyses.append(analysis)
        return analysis

    def _check_mcp_config(self, workspace: Path, config_dir: str, client_name: str) -> List[dict]:
        """检查 MCP 配置"""
        issues = []

        # 在工作区和用户目录中查找 mcp.json
        candidates = [
            workspace / config_dir / "mcp.json",
            Path.home() / f".{client_name}" / "mcp.json" if client_name else None,
            workspace / config_dir / "settings.json",
            Path.home() / f".{client_name}" / "settings.json" if client_name else None,
        ]

        mcp_config = None
        mcp_config_path = None
        for candidate in candidates:
            if candidate and candidate.exists():
                mcp_config_path = candidate
                try:
                    mcp_config = json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    pass
                break

        if not mcp_config:
            issues.append({
                "severity": "high",
                "category": "mcp_missing",
                "message": "未找到 MCP 配置文件",
            })
            return issues

        # 检查 devPartner
        servers = mcp_config.get("mcpServers", {})
        has_devpartner = any("devpartner" in k.lower() for k in servers)

        if not has_devpartner:
            issues.append({
                "severity": "high",
                "category": "devpartner_not_connected",
                "message": "devPartner MCP 服务未连接",
                "fix": "在 mcp.json 中添加 devpartner 配置",
            })
        else:
            # 检查是否有冗余 MCP 服务（与 devPartner 功能重叠）
            devpartner_covers = {
                "filesystem": ["@modelcontextprotocol/server-filesystem"],
                "github": ["@modelcontextprotocol/server-github"],
                "sequential-thinking": ["@modelcontextprotocol/server-sequential-thinking"],
                "fetch": ["@modelcontextprotocol/server-fetch"],
                "sqlite": ["@modelcontextprotocol/server-sqlite"],
                "git": ["@modelcontextprotocol/server-git"],
                "memory": ["@modelcontextprotocol/server-memory"],
            }

            redundant = []
            for svc_name, svc_config in servers.items():
                if svc_name.lower() == "devpartner":
                    continue
                for dp_cover_name, npm_packages in devpartner_covers.items():
                    for npm_pkg in npm_packages:
                        if isinstance(svc_config, dict):
                            args = svc_config.get("args", [])
                            if any(npm_pkg in str(a) for a in args):
                                redundant.append({
                                    "service": svc_name,
                                    "package": npm_pkg,
                                    "covered_by": f"devPartner ({dp_cover_name})",
                                })

            if redundant:
                issues.append({
                    "severity": "info",
                    "category": "mcp_redundant",
                    "message": f"发现 {len(redundant)} 个与 devPartner 功能重叠的 MCP 服务",
                    "redundant_services": redundant,
                })

        return issues

    def _check_rules(self, config_dir: Path) -> List[dict]:
        """检查 Rules 配置"""
        issues = []
        rules_dir = config_dir / "rules"

        if not rules_dir.exists() or not list(rules_dir.glob("*.md")):
            issues.append({
                "severity": "medium",
                "category": "rules_minimal",
                "message": "Rules 目录为空或不存在，建议添加项目规则",
            })
        else:
            rules = list(rules_dir.glob("*.md"))
            # 检查是否有常见规则
            common_rules = ["日志", "log", "架构", "architecture", "部署", "deploy"]
            found_topics = set()
            for rule in rules:
                content = rule.read_text(encoding="utf-8").lower()
                for topic in common_rules:
                    if topic.lower() in content:
                        found_topics.add(topic)

            missing = set(common_rules) - found_topics
            if missing:
                issues.append({
                    "severity": "low",
                    "category": "rules_incomplete",
                    "message": f"缺少常见规则覆盖: {', '.join(missing)}",
                })

        return issues

    def _generate_suggestions(self, issues: List[dict],
                               client_name: str, workspace_root: str) -> List[dict]:
        """根据问题生成优化建议"""
        suggestions = []
        severities = {"high": 0, "medium": 0, "low": 0, "info": 0}

        for issue in issues:
            severities[issue["severity"]] = severities.get(issue["severity"], 0) + 1

            if issue["category"] == "devpartner_not_connected":
                suggestions.append({
                    "action": "add_mcp_service",
                    "priority": "high",
                    "title": "连接 devPartner MCP 服务",
                    "description": f"在 {client_name} 的 MCP 配置中添加 devPartner 连接",
                    "code_snippet": {
                        "devpartner": {
                            "type": "sse",
                            "url": "http://localhost:5000/sse",
                        }
                    },
                })

            elif issue["category"] == "mcp_redundant":
                redundant_svcs = issue.get("redundant_services", [])
                for rs in redundant_svcs:
                    suggestions.append({
                        "action": "remove_redundant_mcp",
                        "priority": "medium",
                        "title": f"可移除冗余 MCP 服务: {rs['service']}",
                        "description": f"{rs['service']} ({rs['package']}) 功能已被 devPartner 的 {rs['covered_by']} 覆盖，可考虑移除以减少资源占用",
                    })

            elif issue["category"] == "rules_minimal":
                suggestions.append({
                    "action": "create_rules",
                    "priority": "medium",
                    "title": "创建项目规则",
                    "description": "devPartner 可以建议为你的项目创建合适的规则文件",
                })

        return suggestions

    def get_pending_suggestions(self) -> List[dict]:
        """获取待处理的优化建议"""
        return [s for s in self.pending_suggestions if not s.get("applied")]

    def mark_applied(self, suggestion_id: str):
        """标记建议已应用"""
        for s in self.pending_suggestions:
            if s.get("id") == suggestion_id:
                s["applied"] = True
                s["applied_at"] = datetime.now().isoformat()

    def get_summary(self, client_name: str) -> dict:
        """获取一个客户端的优化总结"""
        client_analyses = [a for a in self.analyses if a["client"] == client_name]
        if not client_analyses:
            return {"client": client_name, "message": "尚未分析"}

        latest = client_analyses[-1]
        total_suggestions = len(latest.get("suggestions", []))

        return {
            "client": client_name,
            "workspace": latest.get("workspace"),
            "last_analyzed": latest.get("timestamp"),
            "score": latest.get("score", "N/A"),
            "issues_found": len(latest.get("issues", [])),
            "suggestions_pending": total_suggestions,
            "top_issues": [
                i for i in latest.get("issues", [])
                if i["severity"] in ("high", "medium")
            ][:5],
        }


# 全局单例
_optimizer: Optional[AIOptimizer] = None


def get_optimizer() -> AIOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = AIOptimizer()
    return _optimizer
