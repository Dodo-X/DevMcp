"""
优化闭环引擎 (v2.4.0)
======================
核心功能：用户反馈 → 自我检索 → 定位问题 → 自动改进

问题定位维度：
1. 缺少工具 — 对话中需要的功能 MCP 没提供
2. 工具描述弱 — AI 不知道可以用这个工具
3. 工具逻辑错 — 返回结果不准确
4. 规则缺失 — 应该自动触发但没触发
5. 规则过激 — 频繁误触发

优化动作：
- 改进工具描述（description）
- 调整规则触发阈值
- 建议新增工具
- 修复工具逻辑
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional


class OptimizationLoop:
    """优化闭环引擎"""

    def __init__(self):
        pass

    # ── 核心入口：用户反馈驱动的自我检索 ──

    def process_feedback(self, tool_name: str, feedback: str,
                          result_content: str = "",
                          conversation_context: str = "") -> dict:
        """
        处理用户反馈，自动检索问题根因并生成优化方案。

        Args:
            tool_name: 被反馈的工具名
            feedback: 用户反馈内容（如"不对，结果缺少xxx"）
            result_content: 工具返回的结果内容
            conversation_context: 对话上下文

        Returns:
            {
                "diagnosis": {...},       # 诊断结果
                "root_cause": str,        # 根因
                "optimization_plan": {...},  # 优化方案
                "applied": bool,          # 是否已自动应用
            }
        """
        diagnosis = self._diagnose(tool_name, feedback, result_content, conversation_context)
        root_cause = self._determine_root_cause(diagnosis)
        plan = self._create_optimization_plan(diagnosis, root_cause)

        # 记录到数据库
        self._save_diagnosis(tool_name, feedback, diagnosis, root_cause, plan)

        return {
            "diagnosis": diagnosis,
            "root_cause": root_cause,
            "optimization_plan": plan,
            "applied": plan.get("auto_applied", False),
        }

    def _diagnose(self, tool_name: str, feedback: str,
                   result_content: str, context: str) -> dict:
        """
        自我诊断：定位问题维度。
        """
        diagnosis = {
            "tool_name": tool_name,
            "feedback_summary": feedback[:200],
            "possible_causes": [],
            "confidence": 0.0,
        }

        feedback_lower = feedback.lower()

        # ── 维度 1：工具描述弱 ──
        desc_weak_patterns = [
            r"(?:没用|没调|没用到|没调用|不会用|不知道怎么用)",
            r"(?:为什么不用|应该用.*工具|没看到.*调用)",
            r"(?:工具描述|描述不清|不知道怎么触发)",
        ]
        if any(re.search(p, feedback_lower) for p in desc_weak_patterns):
            diagnosis["possible_causes"].append({
                "dimension": "tool_description_weak",
                "detail": "AI 客户端未识别到应调用该工具，可能工具描述不够明确",
                "severity": "medium",
            })

        # ── 维度 2：工具逻辑错 ──
        logic_error_patterns = [
            r"(?:不对|不正确|错误|有问题|不准确|不是我要的)",
            r"(?:结果.*不对|返回.*错|输出.*问题)",
            r"(?:缺少|漏了|没包含|不包括)",
        ]
        if any(re.search(p, feedback_lower) for p in logic_error_patterns):
            # 检查结果内容
            result_issues = self._check_result_quality(result_content)
            diagnosis["possible_causes"].append({
                "dimension": "tool_logic_error",
                "detail": "工具返回结果不准确或不完整",
                "result_issues": result_issues,
                "severity": "high",
            })

        # ── 维度 3：缺少工具 ──
        missing_tool_patterns = [
            r"(?:能不能|可不可以|有没有).{0,10}(?:功能|工具|办法)",
            r"(?:需要一个|缺少一个|没有.*功能)",
            r"(?:要是能|如果有个).{0,10}(?:工具|功能)",
        ]
        if any(re.search(p, feedback_lower) for p in missing_tool_patterns):
            # 提取想要的功能描述
            func_match = re.search(
                r'(?:能不能|可不可以|需要一个|缺少一个|要是能)(.{5,50}?)(?:[。！？\n]|$)',
                feedback
            )
            desired_func = func_match.group(1).strip() if func_match else feedback[:50]
            diagnosis["possible_causes"].append({
                "dimension": "missing_tool",
                "detail": f"用户需要一个新工具: {desired_func}",
                "desired_function": desired_func,
                "severity": "medium",
            })

        # ── 维度 4：规则缺失 ──
        rule_missing_patterns = [
            r"(?:应该自动|为什么不自动|手动.*麻烦|每次都要)",
            r"(?:自动触发|自动执行|自动调用)",
        ]
        if any(re.search(p, feedback_lower) for p in rule_missing_patterns):
            diagnosis["possible_causes"].append({
                "dimension": "rule_missing",
                "detail": "缺少自动触发规则，用户期望自动执行",
                "severity": "medium",
            })

        # ── 维度 5：规则过激 ──
        rule_over_patterns = [
            r"(?:太频繁|一直触发|不停.*调用|太多了|烦)",
            r"(?:不用每次都|不需要.*自动|关掉.*自动)",
        ]
        if any(re.search(p, feedback_lower) for p in rule_over_patterns):
            diagnosis["possible_causes"].append({
                "dimension": "rule_over_trigger",
                "detail": "规则触发过于频繁，应调整阈值或添加冷却",
                "severity": "low",
            })

        # 置信度：有明确原因 → 高置信度
        diagnosis["confidence"] = min(len(diagnosis["possible_causes"]) * 0.3, 1.0)

        return diagnosis

    def _check_result_quality(self, result_content: str) -> list[str]:
        """检查工具返回结果的质量"""
        issues = []
        if not result_content:
            issues.append("返回结果为空")
        elif len(result_content) < 10:
            issues.append("返回结果过短")
        elif "error" in result_content.lower():
            issues.append("返回结果包含错误信息")
        elif "traceback" in result_content.lower():
            issues.append("返回结果包含异常堆栈")
        return issues

    def _determine_root_cause(self, diagnosis: dict) -> str:
        """确定根因"""
        causes = diagnosis.get("possible_causes", [])
        if not causes:
            return "unknown: 无法从反馈中确定根因"

        # 按严重度排序，取最严重的
        severity_order = {"high": 0, "medium": 1, "low": 2}
        causes.sort(key=lambda c: severity_order.get(c.get("severity", "low"), 2))

        primary = causes[0]
        return f"{primary['dimension']}: {primary['detail']}"

    def _create_optimization_plan(self, diagnosis: dict, root_cause: str) -> dict:
        """创建优化方案"""
        plan = {
            "auto_applied": False,
            "actions": [],
            "suggestions": [],
        }

        for cause in diagnosis.get("possible_causes", []):
            dim = cause["dimension"]

            if dim == "tool_description_weak":
                plan["actions"].append({
                    "type": "improve_description",
                    "target": cause.get("tool_name", diagnosis.get("tool_name", "")),
                    "action": "增强工具描述，添加使用场景示例和触发关键词",
                })

            elif dim == "tool_logic_error":
                plan["actions"].append({
                    "type": "fix_tool_logic",
                    "target": cause.get("tool_name", diagnosis.get("tool_name", "")),
                    "action": "检查工具实现逻辑，添加结果验证",
                    "issues": cause.get("result_issues", []),
                })

            elif dim == "missing_tool":
                plan["suggestions"].append({
                    "type": "create_new_tool",
                    "desired_function": cause.get("desired_function", ""),
                    "action": f"建议新增工具以满足需求: {cause.get('desired_function', '')}",
                })

            elif dim == "rule_missing":
                plan["actions"].append({
                    "type": "add_rule",
                    "target": diagnosis.get("tool_name", ""),
                    "action": "添加自动触发规则",
                })

            elif dim == "rule_over_trigger":
                plan["actions"].append({
                    "type": "adjust_rule_threshold",
                    "target": diagnosis.get("tool_name", ""),
                    "action": "提高触发阈值或添加冷却时间",
                })

        return plan

    def _save_diagnosis(self, tool_name: str, feedback: str,
                         diagnosis: dict, root_cause: str, plan: dict):
        """将诊断结果存入数据库"""
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()

            # 根据根因类型写入优化反馈
            feedback_type = root_cause.split(":")[0] if ":" in root_cause else "unknown"
            target_tool = tool_name
            target_rule = ""

            if "rule" in feedback_type:
                target_rule = "auto-log-conversation"

            db.insert_optimization_feedback({
                "source": "user_feedback",
                "feedback_type": feedback_type,
                "target_tool": target_tool,
                "target_rule": target_rule,
                "description": feedback[:500],
                "suggestion": json.dumps(plan, ensure_ascii=False)[:1000],
                "priority": "high" if "error" in feedback_type else "medium",
                "status": "pending",
            })
        except Exception as e:
            print(f"[WARN] 保存诊断结果失败: {e}")

    # ── 批量分析：从数据库中的待处理反馈生成优化报告 ──

    def generate_optimization_report(self) -> dict:
        """
        生成优化报告：汇总所有待处理的反馈，给出优先级排序的优化建议。
        """
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()

            pending = db.get_pending_optimizations(limit=50)
            skill_summary = db.get_skill_summary()
            domain_stats = db.get_domain_stats()

            # 按类型分组
            by_type: dict[str, list] = {}
            for item in pending:
                ft = item.get("feedback_type", "unknown")
                if ft not in by_type:
                    by_type[ft] = []
                by_type[ft].append(item)

            # 生成建议
            suggestions = []
            for ft, items in by_type.items():
                if ft == "tool_description_weak":
                    tools = list(set(i.get("target_tool", "") for i in items if i.get("target_tool")))
                    suggestions.append({
                        "priority": "high",
                        "category": "工具描述优化",
                        "detail": f"以下 {len(tools)} 个工具的描述可能不够清晰：{', '.join(tools[:5])}",
                        "action": "增强工具 description，添加具体使用场景和触发条件",
                    })
                elif ft == "tool_logic_error":
                    suggestions.append({
                        "priority": "critical",
                        "category": "工具逻辑修复",
                        "detail": f"检测到 {len(items)} 次工具返回结果不准确",
                        "action": "检查对应工具的实现逻辑，添加结果验证和错误处理",
                    })
                elif ft == "missing_tool":
                    suggestions.append({
                        "priority": "medium",
                        "category": "新增工具建议",
                        "detail": f"用户 {len(items)} 次提到需要新功能",
                        "action": "分析需求共性，设计新工具",
                    })

            # 技能画像摘要
            skill_insights = []
            for ds in domain_stats:
                skill_insights.append({
                    "domain": ds["skill_domain"],
                    "total_hours": ds.get("total_hours", 0) or 0,
                    "conversation_count": ds.get("cnt", 0),
                })

            return {
                "timestamp": datetime.now().isoformat(),
                "pending_optimizations": len(pending),
                "by_type": {k: len(v) for k, v in by_type.items()},
                "suggestions": suggestions,
                "skill_summary": skill_summary,
                "domain_stats": skill_insights,
            }

        except Exception as e:
            return {"error": str(e)}

    def apply_optimization(self, feedback_id: int) -> dict:
        """应用指定的优化（标记为已处理）"""
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()

            # 获取反馈详情
            rows = db.query_local(
                "SELECT * FROM optimization_feedback WHERE id = ?", (feedback_id,)
            )
            if not rows:
                return {"success": False, "error": f"反馈 ID {feedback_id} 不存在"}

            feedback = rows[0]
            fb_type = feedback.get("feedback_type", "")

            # 根据类型执行不同的优化动作
            result_msg = f"已标记优化 {feedback_id} 为已处理"

            if fb_type == "tool_description_weak":
                result_msg += f"，建议手动优化工具 '{feedback.get('target_tool', '')}' 的描述"
            elif fb_type == "tool_logic_error":
                result_msg += f"，建议检查工具 '{feedback.get('target_tool', '')}' 的实现逻辑"
            elif fb_type == "rule_missing":
                result_msg += "，建议添加自动触发规则"

            db.mark_optimization_applied(feedback_id, result_msg)
            return {"success": True, "message": result_msg}

        except Exception as e:
            return {"success": False, "error": str(e)}


# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
_optimization_loop_instance: Optional[OptimizationLoop] = None

def get_optimization_loop() -> OptimizationLoop:
    global _optimization_loop_instance
    if _optimization_loop_instance is None:
        _optimization_loop_instance = OptimizationLoop()
    return _optimization_loop_instance
