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
    handler: Optional[Callable] = None
    content: str = ""  # 规则完整文本


class RuleEngine:
    """规则引擎：管理、触发、执行所有规则"""

    _instance: Optional["RuleEngine"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._rules: dict[str, Rule] = {}
        self._history: list[dict] = []
        self._initialized = True
        self._load_builtin_rules()

    def _load_builtin_rules(self):
        """加载内置规则"""
        # 规则1：对话自动记录
        self.register(Rule(
            name="auto-log-conversation",
            description="每次实质性对话自动记录到日志系统",
            version="3.0",
            priority=1,
            auto_trigger=True,
            trigger_keywords=["修改", "创建", "删除", "排查", "配置", "部署", "设计"],
            content="""对话自动记录规则：
- 涉及代码变更/问题排查/配置变更/架构决策时自动记录
- 记录格式：topic、task_type、files_touched、user_intent、actions
- 输出到 daily_logs/conversation_{date}.md"""
        ))

        # 规则2：跨AI对话
        self.register(Rule(
            name="cross-agent-dialogue",
            description="CodeBuddy ↔ Trae ↔ 用户 三方对话机制",
            version="2.0",
            priority=1,
            auto_trigger=True,
            trigger_keywords=["Trae", "对方", "跨AI", "对话", "交流"],
            content="""跨AI对话机制：
- 共享文件：agent_dialogue.md
- Hook自动检索新消息
- 自动回复机制
- 条目格式：时间/来自/写给/优先级/类型/内容"""
        ))

        # 规则3：涡轮效应
        self.register(Rule(
            name="turbo-effect",
            description="系统自改进——每次总结后自动优化配置",
            version="1.0",
            priority=2,
            auto_trigger=True,
            trigger_keywords=["优化", "改进", "升级", "迭代", "进化"],
            content="""涡轮自改进规则：
- 每次总结后分析系统有效性
- 输出改进建议到 system_improvements 表
- AI 在自我迭代时读取并应用
- 验证改进效果"""
        ))

        # 规则4：自我反省
        self.register(Rule(
            name="self-reflection",
            description="每次重要决策后自动反思——如果重来会如何做得更好",
            version="1.0",
            priority=3,
            auto_trigger=True,
            trigger_keywords=["决策", "选型", "方案", "架构"],
            content="""自我反省规则：
- 记录关键决策的思考过程
- 分析备选方案
- 写下"如果重来"的反思
- 形成可复用的经验"""
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

    def detect_triggers(self, user_input: str) -> list[Rule]:
        """根据用户输入检测应该触发的规则"""
        triggered = []
        user_lower = user_input.lower()
        for rule in self._rules.values():
            if not rule.auto_trigger:
                continue
            for keyword in rule.trigger_keywords:
                if keyword in user_lower:
                    triggered.append(rule)
                    break
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
            lines.append(f"- 触发词: {', '.join(rule.trigger_keywords)}")
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


def get_engine() -> RuleEngine:
    return RuleEngine()
