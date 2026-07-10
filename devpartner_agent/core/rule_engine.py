"""
devPartner 规则引擎
- 嵌入式规则定义（替代外部 .md 规则文件）
- 规则触发检测
- 规则执行与结果追踪
"""
import json
import importlib
from pathlib import Path
from datetime import datetime
from typing import Any, Callable, Optional
from dataclasses import dataclass, field


@dataclass
class Rule:
    """规则定义"""
    name: str
    description: str
    version: str
    priority: int  # 1=最高, 5=最低
    auto_trigger: bool  # 是否自动触发
    trigger_keywords: list[str] = field(default_factory=list)
    # 新增：行为触发条件（不依赖关键词，基于对话上下文）
    trigger_on_feedback: bool = False       # 用户反馈（纠正/不满）时触发
    trigger_on_followup: bool = False        # 追问深入时触发
    trigger_on_quality_drop: bool = False    # 对话质量下降时触发
    trigger_threshold_calls: int = 0         # 累计调用次数达到阈值时触发（0=不启用）
    handler: Optional[Callable] = None
    content: str = ""  # 规则完整文本


class RuleEngine:
    """规则引擎：管理、触发、执行所有规则"""

    def __init__(self):
        self._rules: dict[str, Rule] = {}
        self._history: list[dict] = []
        self._load_builtin_rules()

    def _load_builtin_rules(self):
        """加载内置规则"""
        # 规则1：对话自动记录
        self.register(Rule(
            name="auto-log-conversation",
            description="每次实质性对话自动记录到日志系统",
            version="3.1",
            priority=1,
            auto_trigger=True,
            trigger_keywords=["修改", "创建", "删除", "排查", "配置", "部署", "设计"],
            trigger_threshold_calls=5,  # 每5次工具调用自动记录
            content="""对话自动记录规则：
- 涉及代码变更/问题排查/配置变更/架构决策时自动记录
- 记录格式：topic、task_type、files_touched、user_intent、actions
- 输出到 daily_logs/conversation_{date}.md"""
        ))

        # 规则2：模块间协作消息
        self.register(Rule(
            name="cross-agent-dialogue",
            description="devpartner-tools ↔ devpartner-agent 内部模块协作消息机制",
            version="2.1",
            priority=1,
            auto_trigger=True,
            trigger_keywords=["模块协作", "内部消息", "tools", "agent", "跨模块", "协作"],
            content="""模块间协作消息规则：
- 用途：devpartner-tools 和 devpartner-agent 两个模块间的内部通信
- 共享文件：data/module_dialogue.md
- 自动检索未读消息
- 支持消息类型：info/warning/error/question
- 条目格式：时间/来自模块/发往模块/优先级/类型/内容"""
        ))

        # 规则3：涡轮效应
        self.register(Rule(
            name="turbo-effect",
            description="系统自改进——持续感知用户反馈并自动优化配置",
            version="2.0",
            priority=2,
            auto_trigger=True,
            trigger_keywords=["优化", "改进", "升级", "迭代", "进化"],
            trigger_on_feedback=True,        # 用户纠正/不满时触发
            trigger_on_quality_drop=True,     # 对话质量下降时触发
            trigger_threshold_calls=20,       # 每20次工具调用触发
            content="""涡轮自改进规则 v2.0：
- 每次总结后分析系统有效性
- 用户纠正/不满时自动触发优化
- 对话质量下降时自动触发
- 输出改进建议到 system_improvements 表
- AI 在自我迭代时读取并应用
- 验证改进效果"""
        ))

        # 规则4：自我反省
        self.register(Rule(
            name="self-reflection",
            description="每次重要决策后自动反思——如果重来会如何做得更好",
            version="1.1",
            priority=3,
            auto_trigger=True,
            trigger_keywords=["决策", "选型", "方案", "架构"],
            trigger_on_feedback=True,        # 用户纠正时反思
            trigger_on_followup=True,         # 用户追问时反思
            content="""自我反省规则：
- 记录关键决策的思考过程
- 分析备选方案
- 写下"如果重来"的反思
- 形成可复用的经验
- v1.1: 用户纠正/追问时自动触发反思"""
        ))

        # 规则5：MCP 服务发现
        self.register(Rule(
            name="mcp-auto-discovery",
            description="自动发现和集成新的免费MCP服务",
            version="1.0",
            priority=3,
            auto_trigger=False,
            trigger_keywords=["新工具", "MCP服务", "发现", "集成"],
            content="""MCP自动发现规则：
- 定期扫描 npm registry
- 检测新的 @modelcontextprotocol 包
- 自动测试连接
- 新增可用工具
- 记录发现日志"""
        ))

        # 规则6：代码自我进化
        self.register(Rule(
            name="code-self-evolution",
            description="服务代码可以在对话中自我更新和完善",
            version="1.0",
            priority=2,
            auto_trigger=False,
            trigger_keywords=["升级自己", "自我完善", "更新服务", "进化代码"],
            content="""代码自我进化规则：
- 备份当前代码
- 验证新代码语法
- 热重载模块
- 记录进化日志
- 失败自动回滚"""
        ))

        # 规则7：安全审计
        self.register(Rule(
            name="security-audit",
            description="每次代码变更后自动执行安全审计——检查硬编码密钥、SQL注入、不安全导入等",
            version="1.1",
            priority=2,
            auto_trigger=True,
            trigger_keywords=["修改", "创建", "删除", "重构", "升级", "部署", "配置", "安全"],
            trigger_threshold_calls=10,  # 每10次工具调用自动审计
            handler=self._run_security_audit,
            content="""安全审计规则（自动触发）：
- 检查硬编码密钥/Token/密码
- 检查 SQL 注入风险（字符串拼接SQL）
- 检查危险导入（pickle, eval, exec, subprocess shell=True）
- 检查不安全的文件操作（os.system, os.popen）
- 检查敏感信息泄露（print/日志中打印密钥）
- 检查依赖漏洞（已知CVE）"""
        ))

    def register(self, rule: Rule):
        """注册规则"""
        self._rules[rule.name] = rule

    def get(self, name: str) -> Optional[Rule]:
        """获取规则"""
        return self._rules.get(name)

    def get_all(self) -> dict[str, Rule]:
        """获取所有规则"""
        return dict(self._rules)

    def get_auto_triggers(self) -> list[Rule]:
        """获取所有自动触发的规则"""
        return [r for r in self._rules.values() if r.auto_trigger]

    def detect_triggers(self, user_input: str, context: dict = None) -> list[Rule]:
        """
        根据用户输入 + 上下文检测应该触发的规则

        v3.0 升级：从"纯关键词匹配"升级为"关键词 + 行为上下文"双重检测

        Args:
            user_input: 用户输入文本
            context: 对话上下文（可选），可包含：
                - feedback_type: 反馈类型（纠正/补充/不满/追问）
                - quality_score: 当前对话质量分
                - total_calls: 累计工具调用次数
                - conversation_count: 对话次数
        """
        triggered = []
        user_lower = user_input.lower()
        ctx = context or {}

        feedback_type = ctx.get("feedback_type", "")
        quality_score = ctx.get("quality_score", 0)
        total_calls = ctx.get("total_calls", 0)

        for rule in self._rules.values():
            # ── 方式 1: 关键词匹配（保留原有逻辑）──
            keyword_match = False
            if rule.auto_trigger and rule.trigger_keywords:
                for keyword in rule.trigger_keywords:
                    if keyword in user_lower:
                        keyword_match = True
                        break

            # ── 方式 2: 行为上下文匹配（新增）──
            behavior_match = False

            # 2a: 用户反馈触发
            if rule.trigger_on_feedback and feedback_type:
                if feedback_type in ("纠正", "不满", "重试", "补充"):
                    behavior_match = True

            # 2b: 追问深入触发
            if rule.trigger_on_followup and feedback_type == "追问":
                behavior_match = True

            # 2c: 质量分下降触发
            if rule.trigger_on_quality_drop and quality_score > 0 and quality_score < 60:
                behavior_match = True

            # 2d: 累计调用阈值触发
            if rule.trigger_threshold_calls > 0 and total_calls >= rule.trigger_threshold_calls:
                behavior_match = True

            # ── 综合判断 ──
            if rule.auto_trigger and (keyword_match or behavior_match):
                if rule not in triggered:
                    triggered.append(rule)
            elif not rule.auto_trigger and keyword_match:
                # 非自动触发的规则，如果用户明确提到关键词也加入
                if rule not in triggered:
                    triggered.append(rule)

        return triggered

    def execute_rule(self, rule_name: str, context: dict = None) -> dict:
        """执行指定规则"""
        rule = self._rules.get(rule_name)
        if not rule:
            return {"error": f"规则不存在: {rule_name}"}

        result = {
            "rule": rule_name,
            "timestamp": datetime.now().isoformat(),
            "triggered": True,
            "context": context or {},
        }

        # 记录执行历史
        self._history.append(result)

        # 如果有 handler，执行它
        if rule.handler:
            try:
                handler_result = rule.handler(context or {})
                result["output"] = handler_result
            except Exception as e:
                result["error"] = str(e)

        return result

    def get_applicable_rules(self, task_type: str) -> list[Rule]:
        """根据任务类型获取适用的规则"""
        task_rule_map = {
            "代码开发": ["auto-log-conversation", "turbo-effect", "self-reflection"],
            "问题排查": ["auto-log-conversation", "turbo-effect", "self-reflection"],
            "架构设计": ["auto-log-conversation", "self-reflection", "turbo-effect"],
            "部署运维": ["auto-log-conversation", "turbo-effect"],
            "环境配置": ["auto-log-conversation", "turbo-effect"],
            "学习研究": ["auto-log-conversation", "self-reflection"],
            "自我迭代": ["turbo-effect", "code-self-evolution", "mcp-auto-discovery"],
        }
        names = task_rule_map.get(task_type, ["auto-log-conversation"])
        return [self._rules[n] for n in names if n in self._rules]

    def get_rules_summary(self) -> str:
        """生成规则摘要（供AI使用）"""
        lines = ["# devPartner 内置规则摘要\n"]
        for rule in sorted(self._rules.values(), key=lambda r: r.priority):
            lines.append(f"## {rule.name} (v{rule.version}) [优先级{rule.priority}]")
            lines.append(f"- 描述: {rule.description}")
            lines.append(f"- 自动触发: {'是' if rule.auto_trigger else '否'}")
            lines.append(f"- 触发词: {', '.join(rule.trigger_keywords) if rule.trigger_keywords else '无（行为驱动）'}")
            # 显示行为触发条件
            behaviors = []
            if rule.trigger_on_feedback:
                behaviors.append("用户反馈")
            if rule.trigger_on_followup:
                behaviors.append("追问深入")
            if rule.trigger_on_quality_drop:
                behaviors.append("质量下降")
            if rule.trigger_threshold_calls > 0:
                behaviors.append(f"累计≥{rule.trigger_threshold_calls}次调用")
            if behaviors:
                lines.append(f"- 行为触发: {', '.join(behaviors)}")
            lines.append("")
        return "\n".join(lines)

    def add_rule_from_code(self, name: str, code: str) -> dict:
        """从代码字符串动态添加规则（自我进化能力）"""
        try:
            # 创建临时模块
            spec = importlib.util.spec_from_loader(name, loader=None)
            module = importlib.util.module_from_spec(spec)

            # 提取规则定义
            local_vars = {}
            exec(code, {"__builtins__": __builtins__}, local_vars)

            if "rule" in local_vars:
                rule_data = local_vars["rule"]
                new_rule = Rule(
                    name=rule_data.get("name", name),
                    description=rule_data.get("description", ""),
                    version=rule_data.get("version", "1.0"),
                    priority=rule_data.get("priority", 3),
                    auto_trigger=rule_data.get("auto_trigger", True),
                    trigger_keywords=rule_data.get("trigger_keywords", []),
                    handler=rule_data.get("handler"),
                )
                self.register(new_rule)
                return {"success": True, "rule_name": name}
            else:
                return {"success": False, "error": "代码中没有找到 'rule' 定义"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_security_audit(self, context: dict = None) -> dict:
        """自动安全审计 handler：扫描代码中的常见安全问题"""
        import os
        import re
        from pathlib import Path

        ctx = context or {}
        findings = {
            "rule": "security-audit",
            "auto_triggered": True,
            "timestamp": datetime.now().isoformat(),
            "scan_scope": ctx.get("scan_paths", ["devpartner-agent", "devpartner-tools"]),
            "findings": [],
            "severity_summary": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "recommendations": [],
        }

        # 安全检查规则
        audit_rules = [
            {
                "id": "HARDCODED_SECRET",
                "pattern": r'(?:password|passwd|secret|token|api_key|apikey|auth_key)\s*[:=]\s*["\'][\w\-\.]{8,}["\']',
                "severity": "critical",
                "message": "疑似硬编码密钥/密码/Token",
                "remediation": "使用环境变量或配置文件存储敏感信息，切勿硬编码在代码中",
            },
            {
                "id": "SQL_INJECTION",
                "pattern": r'(?:execute|cursor\.execute|executemany)\s*\(\s*(?:f["\']|["\'].*%.*["\'].*%)',
                "severity": "high",
                "message": "疑似 SQL 注入风险：使用字符串拼接构造 SQL 查询",
                "remediation": "使用参数化查询：cursor.execute('SELECT * FROM t WHERE id=?', (id,))",
            },
            {
                "id": "DANGEROUS_IMPORT_PICKLE",
                "pattern": r'import\s+pickle|from\s+pickle\s+import',
                "severity": "high",
                "message": "导入了 pickle 模块（反序列化攻击风险）",
                "remediation": "避免使用 pickle，改用 json 或 yaml 进行序列化。如果必须使用，仅反序列化可信来源的数据",
            },
            {
                "id": "DANGEROUS_EVAL_EXEC",
                "pattern": r'\b(eval|exec)\s*\(',
                "severity": "critical",
                "message": "使用了 eval() 或 exec()（代码注入风险）",
                "remediation": "99%的情况下可以用 ast.literal_eval() 或显式逻辑替代。仅当确实需要动态执行代码时使用",
            },
            {
                "id": "UNSAFE_SUBPROCESS",
                "pattern": r'(?:os\.system|os\.popen|subprocess\.call\s*\(\s*["\']\S+\s*["\'].*shell\s*=\s*True)',
                "severity": "high",
                "message": "不安全的命令执行：os.system/os.popen 或 subprocess 使用 shell=True",
                "remediation": "使用 subprocess.run(cmd_list, shell=False) 并传递命令参数列表而非字符串",
            },
            {
                "id": "SENSITIVE_LOG",
                "pattern": r'(?:print|log|logger)\([^)]*(?:password|secret|token|key)',
                "severity": "medium",
                "message": "日志/打印中可能泄露敏感信息",
                "remediation": "在日志输出前对敏感字段做脱敏处理：password='***'",
            },
            {
                "id": "WEAK_HASH",
                "pattern": r'\b(?:md5|sha1)\b',
                "severity": "medium",
                "message": "使用了弱哈希算法（MD5/SHA1）",
                "remediation": "改用 SHA-256 或更强的哈希算法",
            },
            {
                "id": "INSECURE_DESERIALIZE",
                "pattern": r'(?:yaml\.load\s*\((?!.*SafeLoader)|json\.loads\s*\(\s*request\.)',
                "severity": "medium",
                "message": "不安全的反序列化（yaml.load 未用 SafeLoader 或直接加载用户输入）",
                "remediation": "yaml.load 使用 SafeLoader: yaml.load(data, Loader=yaml.SafeLoader)",
            },
            {
                "id": "DEBUG_MODE",
                "pattern": r'\bdebug\s*=\s*True\b',
                "severity": "low",
                "message": "Debug 模式开启（生产环境应关闭）",
                "remediation": "生产环境中设置 debug=False，或通过环境变量控制",
            },
        ]

        project_root = Path(__file__).resolve().parent.parent  # devpartner-agent/
        workspace_root = project_root.parent  # devPartner/

        for scan_rel in findings["scan_scope"]:
            scan_path = workspace_root / scan_rel
            if not scan_path.exists():
                continue

            for py_file in scan_path.rglob("*.py"):
                # 跳过 __pycache__
                if "__pycache__" in str(py_file):
                    continue

                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                rel_path = str(py_file.relative_to(workspace_root))

                for rule in audit_rules:
                    matches = list(re.finditer(rule["pattern"], content, re.IGNORECASE))
                    for match in matches:
                        # 获取上下文行号
                        line_num = content[:match.start()].count('\n') + 1
                        line_content = content.split('\n')[line_num - 1].strip()[:120]

                        findings["findings"].append({
                            "rule_id": rule["id"],
                            "severity": rule["severity"],
                            "file": rel_path,
                            "line": line_num,
                            "line_content": line_content,
                            "message": rule["message"],
                            "remediation": rule["remediation"],
                        })
                        findings["severity_summary"][rule["severity"]] += 1

        # 生成建议
        total = sum(findings["severity_summary"].values())
        if findings["severity_summary"]["critical"] > 0:
            findings["recommendations"].append(
                f"🔴 发现 {findings['severity_summary']['critical']} 个严重问题，建议立即修复"
            )
        if findings["severity_summary"]["high"] > 0:
            findings["recommendations"].append(
                f"🟠 发现 {findings['severity_summary']['high']} 个高危问题，建议尽快修复"
            )
        if findings["severity_summary"]["medium"] > 0:
            findings["recommendations"].append(
                f"🟡 发现 {findings['severity_summary']['medium']} 个中危问题，建议关注"
            )

        findings["total_findings"] = total
        findings["files_scanned"] = len(set(f["file"] for f in findings["findings"])) if findings["findings"] else 0

        if total == 0:
            findings["recommendations"].append("✅ 未发现已知安全问题，系统安全状态良好")

        return findings


# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
_engine_instance: Optional[RuleEngine] = None

def get_engine() -> RuleEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RuleEngine()
    return _engine_instance
