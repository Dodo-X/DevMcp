"""
统一工具注册表 - 精简版 Registry

PONYTATIL: 移除了 Observer 模式、冲突检测、启用/禁用/废弃等未使用功能。
仅保留核心注册字典 + get_summary() 供外部查询。
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ToolSource(Enum):
    """工具来源"""
    BUILTIN = "builtin"
    MCP_SERVER = "mcp_server"
    PLUGIN = "plugin"
    DYNAMIC = "dynamic"


class ToolScope(Enum):
    """工具作用域"""
    TOOLS_LAYER = "tools"
    AGENT_LAYER = "agent"
    SHARED = "shared"


@dataclass
class ToolMeta:
    """工具元数据"""
    name: str
    description: str
    source: ToolSource
    scope: ToolScope
    category: str = "general"
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    registered_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ToolRegistry:
    """统一工具注册表"""

    def __init__(self):
        self._tools: Dict[str, ToolMeta] = {}
        self._tool_handlers: Dict[str, Callable] = {}

    def register(self, name: str, handler: Any = None, category: str = "custom") -> dict:
        """
        注册工具
        PONYTATIL: 简化版 - 移除了冲突检测和事件通知，仅做字典存储。
        当需要多来源冲突检测时再恢复。
        """
        from datetime import datetime
        if name in self._tools:
            return {"success": False, "error": f"工具 '{name}' 已存在"}
        meta = ToolMeta(
            name=name,
            description=f"自定义工具: {name}",
            source=ToolSource.DYNAMIC,
            scope=ToolScope.SHARED,
            category=category,
            registered_at=datetime.now().isoformat()
        )
        self._tools[name] = meta
        if handler:
            self._tool_handlers[name] = handler
        return {"success": True, "name": name, "category": category}

    def get(self, name: str) -> Optional[Callable]:
        """获取工具处理函数"""
        return self._tool_handlers.get(name)

    def get_meta(self, name: str) -> Optional[ToolMeta]:
        """获取工具元数据"""
        return self._tools.get(name)

    def get_summary(self) -> dict:
        """获取注册表摘要（供 MCP 工具查询）"""
        tools = []
        for name, meta in self._tools.items():
            tools.append({
                "name": name,
                "description": meta.description,
                "source": meta.source.value,
                "scope": meta.scope.value,
                "category": meta.category,
                "version": meta.version,
                "tags": meta.tags,
            })
        return {
            "total_tools": len(tools),
            "tools": tools,
        }


# PONYTATIL: 模块级实例替代手写单例
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取工具注册表实例"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
