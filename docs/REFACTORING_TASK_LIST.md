# 📋 DevPartner v5.2 → v6.0 重构任务清单

> **目标**: 解决历史遗留问题，实现 LLM 完全驱动，精简代码，优化数据模型  
> **状态**: 进行中 | **预计完成**: 2026-07-03  
> **验收标准**: 用户逐一比对确认

---

## ✅ 任务总览

| # | 问题 | 优先级 | 复杂度 | 预计耗时 | 状态 |
|---|------|--------|--------|---------|------|
| 1 | 融合硬编码到 LLM 提示词 + 清理冗余代码 | 🔴 P0 | 高 | 2h | ⏳ 进行中 |
| 2 | skills_observed 增量合并逻辑 | 🟡 P1 | 中 | 30min | ⏳ 待处理 |
| 3 | improvement_log 表结构优化 | 🟡 P1 | 中 | 45min | ⏳ 待处理 |
| 4 | 客户端分析 Few-shot 示例增强 | 🟢 P2 | 低 | 20min | ⏳ 待处理 |
| 5 | 定时汇总触发机制 | 🟢 P2 | 中 | 40min | ⏳ 待处理 |
| 6 | 画像追溯能力增强 | 🟡 P1 | 中 | 30min | ⏳ 待处理 |
| 7 | MCP 工具精简（去掉 reasoning/discovery） | 🔴 P0 | 低 | 15min | ⏳ 待处理 |

---

## 任务 1: 融合硬编码到 LLM 提示词 + 清理冗余代码

### 🎯 目标
将 `conversation_analyzer.py`、`auto_analyzer.py`、`user_profile_service.py` 中的所有硬编码规则融合到 `llm_unified_analyzer.py` 的提示词中，然后删除废弃代码。

### 📝 当前硬编码位置识别

#### 1.1 conversation_analyzer.py (654行)
```python
# ❌ 需要删除的硬编码：
SKILL_DOMAINS = {  # 8个领域, 100+关键词
    "Python": ["python", "django", "flask", ...],
    "前端": ["react", "vue", "angular", ...],
    ...
}

MCP_TOOL_PATTERNS = {  # 7个正则模式
    "read_file": r"(?:读取?|查看|打开)...",
    ...
}

COMPLEXITY_PATTERNS = { ... }  # 复杂度评估规则
FEEDBACK_PATTERNS = [...]      # 反馈检测规则
```

**解决方案**: 这些已部分在 `llm_unified_analyzer.py` 的 `analyze_conversation()` 方法中通过 Prompt 实现。需要：
- ✅ 完善 Prompt 模板（包含所有原规则的语义描述）
- ✅ 删除 conversation_analyzer.py 中的字典/正则定义
- ✅ 保留 `analyze_and_store()` 方法作为调用入口（委托给 LLM 引擎）

#### 1.2 auto_analyzer.py (批量分析)
```python
# 当前调用方式：
analyzer = get_analyzer()  # 使用旧的 ConversationAnalyzer
analysis = analyzer.analyze(raw_content)  # 调用硬编码方法
```

**解决方案**: 
- ✅ 改为调用 `LLMUnifiedAnalyzer.analyze_conversation()`
- ✅ 删除 `auto_analyzer.py` 或简化为薄封装层

#### 1.3 user_profile_service.py (141行)
```python
# 当前：硬编码字段映射
def apply_user_traits(traits):
    # skills_observed → user_skills 表（固定映射）
    # behavior_notes → improvement_log 表（固定分类）
    # mistakes → improvement_log 表（固定分类）
```

**解决方案**: 
- ✅ 已在 `llm_unified_analyzer.py` 的 `apply_user_traits()` 方法中实现
- ✅ 删除 `user_profile_service.py` 中的旧逻辑

### 🔧 执行步骤

**Step 1**: 增强 LLM 统一引擎提示词（已完成基础版，需完善细节）  
**Step 2**: 更新 `conversation_analyzer_v2.py` 为默认版本  
**Step 3**: 标记旧方法为 `@deprecated`  
**Step 4**: 清理未使用的导入和常量  

### 📊 预期成果
- 删除 **~800 行**硬编码规则代码
- `conversation_analyzer.py`: 654行 → ~150行（保留接口兼容层）
- `user_profile_service.py`: 141行 → ~20行（委托给LLM引擎）
- `auto_analyzer.py`: 简化为 ~50行（批量调度器）

---

## 任务 2: skills_observed 增量合并逻辑

### 🎯 目标
防止 user_skills 表快速膨胀，实现智能去重和置信度更新。

### 🐛 当前问题
```python
# 每次都直接 INSERT，不检查是否已存在
db.upsert_user_skills(skill, {
    "skill_level": "intermediate",
    ...
})
```
**后果**: 同一技能重复插入多次（如"Python"出现10次就插入10条）

### ✅ 解决方案

在 `llm_unified_analyzer.py` 的 `apply_user_traits()` 方法中增加：

```python
def _merge_skill_incremental(self, skill_name: str, context: dict) -> dict:
    """
    技能增量合并逻辑
    
    1. 查询 skill 是否已存在
       - 存在: 更新 last_seen, confidence += 0.1, 合并 sub_skills
       - 不存在: 新增记录
    2. 返回操作结果（insert / update / merge）
    """
    db = get_db()
    
    # 查询现有记录
    existing = db.query_user_skill(skill_name)
    
    if existing:
        # 已存在 → 增量更新
        new_confidence = min(existing["confidence"] + 0.1, 1.0)
        new_sub_skills = self._merge_sub_skills(
            existing.get("sub_skills", ""),
            context.get("sub_skills", [])
        )
        
        db.update_user_skill(skill_name, {
            "confidence": new_confidence,
            "sub_skills": new_sub_skills,
            "last_seen": datetime.now().isoformat(),
            "evidence_count": existing.get("evidence_count", 1) + 1,
        })
        
        return {"action": "updated", "skill": skill_name, "confidence": new_confidence}
    else:
        # 不存在 → 新增
        db.insert_user_skill(skill_name, {
            "confidence": 0.5,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "evidence_count": 1,
            **context
        })
        
        return {"action": "inserted", "skill": skill_name, "confidence": 0.5}
```

### 📊 数据库 Schema 变更
```sql
-- user_skills 表新增字段
ALTER TABLE user_skills ADD COLUMN confidence REAL DEFAULT 0.5;
ALTER TABLE user_skills ADD COLUMN first_seen TEXT;
ALTER TABLE user_skills ADD COLUMN last_seen TEXT;
ALTER TABLE user_skills ADD COLUMN evidence_count INTEGER DEFAULT 1;

-- 创建唯一索引防重复
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_skills_unique 
ON user_skills(skill_name);
```

---

## 任务 3: improvement_log 表结构优化

### 🎯 目标
解决 9 个维度全部塞入一张表导致的字段过多、查询不便问题。

### 🐛 当前问题
```python
# 所有维度都写入同一张表 improvement_log：
behavior_notes → category="user_behavior_profile"
communication_style → category="user_communication_profile"
decision_pattern → category="user_communication_profile"
emotional_state → feedback_type="emotional_state"
mistakes → category="user_lesson_learned"
strengths → category="user_strength"
learning_progress → （缺失！）
```

**问题**:
- 字段散乱，难以聚合查询
- 无法区分"行为特征"vs"错误记录"vs"优势"
- 缺少 learning_progress 维度

### ✅ 方案 A: 拆分为多表（推荐）

```sql
-- 1. user_behavior 表（行为/沟通/决策/情绪）
CREATE TABLE IF NOT EXISTS user_behavior (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    behavior_type TEXT NOT NULL,  -- communication_style / decision_pattern / emotional_state
    content TEXT NOT NULL,
    source TEXT,
    conversations_id INTEGER,
    recorded_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (conversations_id) REFERENCES conversations(id)
);

-- 2. user_mistakes 表（错误记录）
CREATE TABLE IF NOT EXISTS user_mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mistake_desc TEXT NOT NULL,
    severity TEXT DEFAULT 'medium',
    lesson_learned TEXT,
    source_conversation_id INTEGER,
    occurred_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (source_conversation_id) REFERENCES conversations(id)
);

-- 3. user_strengths 表（优势）
CREATE TABLE IF NOT EXISTS user_strengths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strength_desc TEXT NOT NULL,
    evidence TEXT,
    source_conversation_id INTEGER,
    discovered_at TEXT DEFAULT (datetime('now'))
);

-- 4. learning_observations 表（学习进度）
CREATE TABLE IF NOT EXISTS learning_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT NOT NULL,
    progress_level TEXT,  -- beginner / intermediate / advanced / expert
    observation TEXT,
    next_steps TEXT,
    period_start TEXT,
    period_end TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### ✅ 方案 B: 单表 + JSON 字段（备选）

如果不想拆分表，可以使用 JSON 字段存储维度：

```sql
ALTER TABLE improvement_log ADD COLUMN dimensions JSON;
-- 存储格式:
-- {"behavior_notes": "...", "communication_style": "...", "mistakes": [...]}
```

**建议**: 采用**方案 A（拆分表）**，理由：
- ✅ 查询性能更好（可建索引）
- ✅ 数据模型清晰
- ✅ 符合数据库范式
- ✅ 便于后续扩展

---

## 任务 4: 客户端分析 Few-shot 示例增强

### 🎯 目标
提供标准化示例，确保不同客户端（CodeBuddy/Cursor/Trae）输出一致的用户画像。

### 🐛 当前问题
客户端自行分析用户画像时质量不一致，缺少统一标准。

### ✅ 解决方案

在 `llm_unified_analyzer.py` 中增加 Few-shot Prompt：

```python
USER_PROFILE_FEW_SHOT_EXAMPLES = """
## 示例 1: 前端开发者对话
输入对话:
"""
我在用 React + TypeScript 开发一个电商项目，遇到了 Redux Toolkit 的异步 action 类型定义错误。
"""

期望输出:
{
  "skills_observed": ["React 开发", "TypeScript 使用", "状态管理"],
  "behavior_notes": "倾向于同时提出多个相关问题，希望获得系统性解答",
  "tech_interests": ["现代前端框架", "类型安全"],
  "areas_for_growth": ["TypeScript 高级类型"],
  "mistakes": ["async/await 与 Promise 混用导致类型推断失败"],
  "strengths": ["能够清晰描述技术问题上下文"],
  "learning_progress": {
    "current_level": "intermediate",
    "target_level": "advanced",
    "gap_analysis": "需要掌握泛型、条件类型等高级特性"
  }
}

## 示例 2: 后端开发者对话
输入对话:
"""
Django ORM 的 N+1 查询问题怎么解决？我试了 select_related 但还是慢。
"""

期望输出:
{
  "skills_observed": ["Python/Django", "ORM 优化", "数据库性能调优"],
  "behavior_notes": "遇到性能问题时会主动尝试常见方案再求助",
  "tech_interests": ["后端架构", "数据库优化"],
  "areas_for_growth": ["SQL 执行计划分析", "缓存策略设计"],
  "mistakes": ["混淆 select_related 和 prefetch_related 适用场景"],
  "strengths": ["有性能优化意识", "熟悉 Django 生态"],
  "learning_progress": {
    "current_level": "intermediate",
    "target_level": "advanced",
    "gap_analysis": "需要深入理解数据库索引和查询优化原理"
  }
}
"""

在 request_user_profile_analysis() 时附带此示例。
```

---

## 任务 5: 定时汇总触发机制

### 🎯 目标
增加定期自动生成成长路线图的能力，而非仅依赖单次对话触发。

### 🐛 当前问题
只有"每次对话结束时触发"，缺少周期性汇总机制。

### ✅ 解决方案

#### 5.1 新增定时任务模块
```python
# devpartner_agent/core/scheduler.py

import schedule
import threading
from datetime import datetime

class ProfileScheduler:
    """用户画像定时汇总调度器"""
    
    def __init__(self):
        self._running = False
        self._thread = None
    
    def start(self):
        """启动定时任务"""
        if self._running:
            return
            
        # 每天 23:00 触发每日画像汇总
        schedule.every().day.at("23:00").do(self._daily_summary)
        
        # 每周一 09:00 触发每周成长路线图
        schedule.every().monday.at("09:00").do(self._weekly_roadmap)
        
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._running = True
        logger.info("✅ 画像定时调度器已启动")
    
    def _daily_summary(self):
        """每日汇总"""
        from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer
        
        analyzer = get_unified_analyzer()
        
        # 收集今日所有对话
        today_data = self._collect_daily_conversations()
        
        # LLM 生成每日画像摘要
        summary = analyzer.generate_profile_summary(
            scope="daily",
            data=today_data,
            date=datetime.now().strftime("%Y-%m-%d")
        )
        
        # 存储到 learning_observations 表
        self._save_summary(summary, period="daily")
        
        logger.info(f"📊 每日画像汇总完成: {summary.get('total_conversations', 0)} 条对话")
    
    def _weekly_roadmap(self):
        """每周成长路线图"""
        analyzer = get_unified_analyzer()
        
        week_data = self._collect_weekly_conversations()
        
        roadmap = analyzer.generate_growth_roadmap(
            scope="weekly",
            data=week_data,
            period_start=(datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
            period_end=datetime.now().strftime("%Y-%m-%d")
        )
        
        self._save_roadmap(roadmap)
        
        logger.info("🗺️ 每周成长路线图已生成")
```

#### 5.2 在 server.py 启动时注册
```python
# server.py 主入口
from devpartner_agent.core.scheduler import ProfileScheduler

def main():
    # ... 其他初始化 ...
    
    # 启动画像定时调度器
    scheduler = ProfileScheduler()
    scheduler.start()
    
    # 启动 Web 服务
    app.run(host='0.0.0.0', port=8082)
```

---

## 任务 6: 画像追溯能力增强

### 🎯 目标
支持追溯技能来源（哪个对话、何时提取），提升数据分析可信度。

### 🐛 当前问题
无法回答："这个技能是什么时候学的？从哪次对话发现的？"

### ✅ 解决方案

#### 6.1 数据库 Schema 增强
```sql
-- user_skills 表新增字段
ALTER TABLE user_skills ADD COLUMN source_conversation_id INTEGER;
ALTER TABLE user_skills ADD COLUMN source_timestamp TEXT;
ALTER TABLE user_skills ADD COLUMN extraction_method TEXT;  -- llm / rule / manual

-- 外键约束
ALTER TABLE user_skills ADD CONSTRAINT fk_skill_source 
FOREIGN KEY (source_conversation_id) REFERENCES conversations(id);

-- 索引优化查询
CREATE INDEX idx_skills_source ON user_skills(source_conversation_id);
CREATE INDEX idx_skills_timestamp ON user_skills(source_timestamp);
```

#### 6.2 在 apply_user_traits() 中记录来源
```python
def apply_user_traits(self, traits, source="unified_analyzer", conversation_id=None):
    for skill in traits.get("skills_observed", []):
        result = self._merge_skill_incremental(skill, {
            "sub_skills": [],
            "source_conversation_id": conversation_id,
            "source_timestamp": datetime.now().isoformat(),
            "extraction_method": "llm_qwen3.5",
            "evidence": f"从对话 #{conversation_id} 中提取"
        })
```

#### 6.3 新增查询 API
```python
def query_skill_lineage(self, skill_name: str) -> list:
    """
    查询技能的学习轨迹
    
    Returns:
        [
            {
                "timestamp": "2026-07-01T10:30:00",
                "conversation_id": 123,
                "confidence": 0.6,
                "event": "首次发现",
                "context": "用户讨论 React Hooks"
            },
            {
                "timestamp": "2026-07-02T14:20:00",
                "conversation_id": 145,
                "confidence": 0.75,
                "event": "能力提升",
                "context": "用户独立解决 Redux 问题"
            },
            ...
        ]
    """
    db = get_db()
    lineage = db.query_skill_history(skill_name)
    
    return sorted(lineage, key=lambda x: x["timestamp"])
```

---

## 任务 7: MCP 工具精简

### 🎯 目标
遵循设计原则，移除不适合暴露为 MCP 工具的功能。

### 📋 设计原则回顾
1. **工具 = 客户端可见的接口，不是内部模块**
2. **内部逻辑不应暴露为 MCP 工具**
3. **每个工具必须有明确、唯一的客户端使用场景**
4. **能用 LLM 做的，就不要单独做一个工具**
5. **能用配置做的，就不要单独做一个工具**
6. **低频工具不值得占用 MCP 命名空间**

### 🗑️ 待删除工具

#### 7.1 reasoning.py（推理工具）
**删除原因**:
- ❌ 推理是 LLM 内部能力，不应暴露为工具
- ❌ 客户端不需要显式调用"推理"
- ✅ 应该通过 LLM Prompt 隐式实现

**替代方案**:
```python
# 在需要推理的场景，直接使用 LLM：
result = analyzer.analyze_with_reasoning(content)
# 推理过程在 LLM 内部完成，不暴露给客户端
```

#### 7.2 mcp_discovery.py（发现工具）
**删除原因**:
- ❌ 工具发现是内部管理功能
- ❌ 客户端不需要主动发现可用工具
- ✅ 应该由服务端启动时自动注册并广播

**替代方案**:
```python
# 服务端启动时自动加载工具列表
def load_available_tools():
    tools = scan_tools_directory()
    broadcast_to_clients(tools)  # 通过初始化消息发送
```

### ✅ 保留的工具列表（精简后）
```
devpartner_tools/tools/
├── filesystem.py          # ✅ 文件读写（高频使用）
├── git_operations.py      # ✅ Git 操作（核心需求）
├── web_requests.py        # ✅ HTTP 请求（通用能力）
└── system_utils.py        # ✅ 系统命令（调试必需）
```

**删除的工具**:
```
├── reasoning.py           # ❌ 删除（LLM 内部能力）
└── mcp_discovery.py       # ❌ 删除（内部管理功能）
```

### 📊 精简效果
- 工具数量: 6个 → **4个** (减少33%)
- MCP 命名空间: 更清晰
- 客户端复杂度: 降低

---

## 📈 总体预期成果

### 代码量变化
| 模块 | 改造前 | 改造后 | 减少 |
|------|-------|-------|------|
| conversation_analyzer.py | 654行 | ~150行 | **77%↓** |
| user_profile_service.py | 141行 | ~20行 | **86%↓** |
| auto_analyzer.py | 200行 | ~50行 | **75%↓** |
| reasoning.py | 120行 | **删除** | **100%↓** |
| mcp_discovery.py | 80行 | **删除** | **100%↓** |
| **总计** | **~1195行** | **~220行** | **82%↓** |

### 数据模型优化
- user_skills 表: 增加 5 个字段（confidence, first_seen, last_seen 等）
- improvement_log 表: 拆分为 4 张表（behavior/mistakes/strengths/learning）
- 新增 scheduler.py 定时任务模块
- 新增 skill_lineage 查询 API

### 功能增强
- ✅ 技能增量合并（防膨胀）
- ✅ Few-shot 示例（保证一致性）
- ✅ 定时汇总（每日/每周）
- ✅ 画像追溯（完整学习轨迹）
- ✅ 工具精简（聚焦核心能力）

---

## 🎬 执行顺序建议

### Phase 1: 基础清理（今天完成）
1. ✅ **任务 7**: 删除 reasoning.py 和 mcp_discovery.py（最简单，立竿见影）
2. ✅ **任务 1**: 融合硬编码到 LLM 提示词（核心工作）

### Phase 2: 数据模型优化（明天完成）
3. ✅ **任务 2**: 实现 skills 增量合并
4. ✅ **任务 3**: 拆分 improvement_log 表
5. ✅ **任务 6**: 增加画像追溯字段

### Phase 3: 功能增强（后天完成）
6. ✅ **任务 4**: 增加 Few-shot 示例
7. ✅ **任务 5**: 实现定时汇总机制

---

## ✅ 验收检查清单

用户验收时请逐项核对：

### 代码层面
- [ ] conversation_analyzer.py 无硬编码字典/正则（仅保留接口）
- [ ] user_profile_service.py 委托给 LLM 引擎
- [ ] reasoning.py 和 mcp_discovery.py 已删除
- [ ] 代码总量减少 >70%
- [ ] 无编译错误/warning

### 数据层面
- [ ] user_skills 表有 confidence/first_seen/last_seen 字段
- [ ] improvement_log 已拆分或使用 JSON 字段
- [ ] 技能不会重复插入（有唯一索引）
- [ ] 可查询技能来源（source_conversation_id）

### 功能层面
- [ ] 对话分析结果与原来一致或更优
- [ ] 用户画像包含 Few-shot 示例
- [ ] 定时任务正常触发（可通过日志验证）
- [ ] 画像追溯 API 可用

### 文档层面
- [ ] README.md 更新（反映新架构）
- [ ] CHANGELOG.md 记录本次变更
- [ ] 数据库迁移脚本可用
- [ ] 测试用例覆盖新功能

---

**文档版本**: v1.0  
**创建时间**: 2026-07-03  
**维护者**: AI Assistant  
**下一步**: 开始执行任务 1（融合硬编码到 LLM）