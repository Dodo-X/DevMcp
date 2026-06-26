"""
统一工具注册表 - Tool Registry 模式

借鉴 Cline/Roo Code 的 MCP 管理架构：
- 所有工具注册到统一 Registry
- 支持按需启用/禁用
- 工具去重检测
- 动态加载/卸载
- 与能力授权引擎集成

设计模式：Registry 模式 + Observer 模式
"""

import json
from typing import Dict, List, Set, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ToolSource(Enum):
    """工具来源"""
    BUILTIN = "builtin"         # 内置工具
    MCP_SERVER = "mcp_server"   # 外部 MCP 服务
    PLUGIN = "plugin"           # 插件
    DYNAMIC = "dynamic"         # 动态注册


class ToolScope(Enum):
    """工具作用域"""
    TOOLS_LAYER = "tools"    # 纯工具层
    AGENT_LAYER = "agent"    # 智能管家层
    SHARED = "shared"        # 共享


@dataclass
class ToolMeta:
    """工具元数据"""
    name: str
    description: str
    source: ToolSource
    scope: ToolScope
    enabled: bool = True
    category: str = "general"
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    deprecated: bool = False
    deprecated_message: str = ""
    registered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    call_count: int = 0
    last_called: str = ""
    avg_duration_ms: float = 0.0


@dataclass
class RegistryEvent:
    """注册表事件"""
    event_type: str  # "register" | "unregister" | "enable" | "disable" | "deprecate" | "conflict"
    tool_name: str
    timestamp: str
    details: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """统一工具注册表 - 单例模式"""
    
    _instance: Optional["ToolRegistry"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._tools: Dict[str, ToolMeta] = {}
        self._tool_handlers: Dict[str, Callable] = {}
        self._events: List[RegistryEvent] = []
        self._observers: List[Callable] = []
        self._conflicts: Dict[str, List[str]] = {}
    
    def register(self, name: str, handler: Callable, meta: ToolMeta) -> bool:
        """
        注册工具
        
        Args:
            name: 工具名称
            handler: 工具处理函数
            meta: 工具元数据
        
        Returns:
            bool: 是否注册成功
        """
        # 检测重复
        if name in self._tools:
            existing = self._tools[name]
            if existing.source != meta.source:
                # 不同来源的同名工具，记录冲突
                self._conflicts.setdefault(name, []).append(existing.source.value)
                self._conflicts[name].append(meta.source.value)
                self._emit_event(RegistryEvent(
                    event_type="conflict",
                    tool_name=name,
                    timestamp=datetime.now().isoformat(),
                    details={
                        "existing_source": existing.source.value,
                        "new_source": meta.source.value,
                        "existing_scope": existing.scope.value,
                        "new_scope": meta.scope.value,
                    }
                ))
                return False
        
        meta.registered_at = datetime.now().isoformat()
        self._tools[name] = meta
        self._tool_handlers[name] = handler
        
        self._emit_event(RegistryEvent(
            event_type="register",
            tool_name=name,
            timestamp=meta.registered_at,
            details={"source": meta.source.value, "scope": meta.scope.value, "category": meta.category}
        ))
        
        return True
    
    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            del self._tool_handlers[name]
            self._emit_event(RegistryEvent(
                event_type="unregister",
                tool_name=name,
                timestamp=datetime.now().isoformat()
            ))
            return True
        return False
    
    def enable(self, name: str) -> bool:
        """启用工具"""
        if name in self._tools:
            self._tools[name].enabled = True
            self._emit_event(RegistryEvent(
                event_type="enable",
                tool_name=name,
                timestamp=datetime.now().isoformat()
            ))
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """禁用工具"""
        if name in self._tools:
            self._tools[name].enabled = False
            self._emit_event(RegistryEvent(
                event_type="disable",
                tool_name=name,
                timestamp=datetime.now().isoformat()
            ))
            return True
        return False
    
    def deprecate(self, name: str, message: str) -> bool:
        """标记工具为废弃"""
        if name in self._tools:
            self._tools[name].deprecated = True
            self._tools[name].deprecated_message = message
            self._emit_event(RegistryEvent(
                event_type="deprecate",
                tool_name=name,
                timestamp=datetime.now().isoformat(),
                details={"message": message}
            ))
            return True
        return False
    
    def get(self, name: str) -> Optional[Callable]:
        """获取工具处理函数"""
        meta = self._tools.get(name)
        if meta and meta.enabled and not meta.deprecated:
            # 更新调用统计
            meta.call_count += 1
            meta.last_called = datetime.now().isoformat()
            return self._tool_handlers.get(name)
        return None
    
    def get_meta(self, name: str) -> Optional[ToolMeta]:
        """获取工具元数据"""
        return self._tools.get(name)
    
    def list_tools(self, scope: Optional[ToolScope] = None,
                   category: Optional[str] = None,
                   enabled_only: bool = True) -> List[ToolMeta]:
        """列出所有工具"""
        result = list(self._tools.values())
        
        if scope:
            result = [t for t in result if t.scope == scope]
        if category:
            result = [t for t in result if t.category == category]
        if enabled_only:
            result = [t for t in result if t.enabled and not t.deprecated]
        
        return sorted(result, key=lambda t: t.name)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取注册表统计"""
        tools = list(self._tools.values())
        enabled = [t for t in tools if t.enabled and not t.deprecated]
        deprecated = [t for t in tools if t.deprecated]
        disabled = [t for t in tools if not t.enabled]
        
        by_scope = {}
        for scope in ToolScope:
            by_scope[scope.value] = len([t for t in tools if t.scope == scope])
        
        by_source = {}
        for source in ToolSource:
            by_source[source.value] = len([t for t in tools if t.source == source])
        
        by_category = {}
        for t in tools:
            by_category[t.category] = by_category.get(t.category, 0) + 1
        
        # 最常用工具
        top_used = sorted(enabled, key=lambda t: t.call_count, reverse=True)[:10]
        
        return {
            "total": len(tools),
            "enabled": len(enabled),
            "disabled": len(disabled),
            "deprecated": len(deprecated),
            "conflicts": len(self._conflicts),
            "by_scope": by_scope,
            "by_source": by_source,
            "by_category": by_category,
            "top_used": [{"name": t.name, "calls": t.call_count, "last": t.last_called} for t in top_used],
            "recent_events": [{"type": e.event_type, "tool": e.tool_name, "ts": e.timestamp} for e in self._events[-10:]],
        }
    
    def get_conflicts(self) -> Dict[str, List[str]]:
        """获取工具冲突"""
        return dict(self._conflicts)
    
    def observe(self, callback: Callable) -> None:
        """注册观察者"""
        self._observers.append(callback)
    
    def _emit_event(self, event: RegistryEvent) -> None:
        """发送事件"""
        self._events.append(event)
        for observer in self._observers:
            try:
                observer(event)
            except Exception:
                pass
    
    def export_manifest(self) -> str:
        """导出工具清单（JSON）"""
        tools = []
        for name, meta in self._tools.items():
            tools.append({
                "name": name,
                "description": meta.description,
                "source": meta.source.value,
                "scope": meta.scope.value,
                "category": meta.category,
                "enabled": meta.enabled,
                "deprecated": meta.deprecated,
                "version": meta.version,
                "tags": meta.tags,
                "call_count": meta.call_count,
            })
        
        return json.dumps({
            "registry_version": "2.0.0",
            "exported_at": datetime.now().isoformat(),
            "total_tools": len(tools),
            "tools": tools,
            "conflicts": {k: v for k, v in self._conflicts.items()},
        }, ensure_ascii=False, indent=2)


def get_tool_registry() -> ToolRegistry:
    """获取工具注册表实例"""
    return ToolRegistry()


def deprecated_tool(message: str = ""):
    """
    废弃工具装饰器
    
    使用示例:
        @deprecated_tool("请使用 new_tool 替代")
        def old_tool(...):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            import json
            return json.dumps({
                "success": False,
                "deprecated": True,
                "message": message or f"工具 '{func.__name__}' 已废弃，请使用新版本",
                "migration_guide": "详见 README.md",
            }, ensure_ascii=False)
        
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        wrapper._deprecated = True
        wrapper._deprecated_message = message
        return wrapper
    return decorator
