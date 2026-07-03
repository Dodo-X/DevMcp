# DevPartner LLM 驱动架构重构指南 v6.0

## 📋 项目背景与痛点诊断

### ❌ 当前问题：代码繁杂冗余，维护成本高

通过对项目全面扫描，发现以下 **硬编码数据分析逻辑** 散落在各模块中：

| 模块 | 代码行数 | 硬编码内容 | 维护成本 |
|------|---------|-----------|---------|
| `conversation_analyzer.py` | 654行 | SKILL_DOMAINS (100+关键词)<br>MCP_TOOL_PATTERNS (7个正则)<br>COMPLEXITY_PATTERNS (3级)<br>FEEDBACK_PATTERNS (5种) | 🔴 **极高**<br>新增领域/工具需手动添加 |
| `daily_summary.py` | 704+行 | Markdown 报告模板<br>数据格式化逻辑<br>字段映射规则 | 🔴 **高**<br>输出格式固定难调整 |
| `self_iterate.py` | 1697行 | 建议生成规则引擎<br>数据收集SQL查询<br>报告生成模板 | 🔴 **高**<br>建议质量依赖人工规则 |
| `user_profile_service.py` | 141行 | 字段映射关系<br>分类处理分支 | 🟡 **中**<br>新特征类型需改代码 |
| `upgrade_to_v5.py` | 450行 | Schema验证逻辑<br>约束检查规则 | 🟡 **中**<br>版本升级需同步修改 |

**总硬编码量**: ~3600+ 行规则代码  
**核心问题**: 规则分散、逻辑耦合、扩展困难、迭代成本高

---

## 🎯 解决方案：LLM 统一提示词体系

### ✅ 核心思路

```
┌─────────────────────────────────────────────────────┐
│                 原架构（硬编码）                      │
│                                                     │
│  conversation_analyzer ──→ 正则匹配 + 字典查找      │
│       ↓                                             │
│  daily_summary ──→ 模板填充 + 格式化                │
│       ↓                                             │
│  self_iterate ──→ 规则引擎 + 条件判断               │
│       ↓                                             │
│  user_profile_service ──→ 字段映射 + 分支逻辑        │
│                                                     │
│  ❌ 代码重复、规则散落、难以统一优化                  │
└─────────────────────────────────────────────────────┘

                    ⬇️ 重构为

┌─────────────────────────────────────────────────────┐
│              新架构（LLM 驱动）                       │
│                                                     │
│  所有模块 ──→ LLMUnifiedAnalyzer (单例)             │
│                  ↓                                  │
│         llama-cpp-python + Qwen3.5-9B               │
│                  ↓                                  │
│      结构化 Prompt 模板 → JSON 输出                 │
│                                                     │
│  ✅ 统一入口、智能推理、灵活可配                      │
└─────────────────────────────────────────────────────┘
```

---

## 📦 新增核心组件

### 1️⃣ LLM 统一分析引擎

**文件位置**: [llm_unified_analyzer.py](../devpartner_agent/core/llm_unified_analyzer.py)

**核心能力**:
- ✅ 对话内容深度分析（替代 conversation_analyzer 硬编码）
- ✅ 每日工作总结生成（替代 daily_summary 模板）
- ✅ 自我改进建议生成（替代 self_iterate 规则引擎）
- ✅ 用户画像智能融合（替代 user_profile_service 映射）
- ✅ 数据库 Schema 分析（替代升级脚本验证）

**技术特性**:
- 单例模式 + 懒加载（复用 LLMService 实例）
- 双模式运行（LLM 可用时智能分析，不可用时优雅降级）
- JSON 输出约束（结构化 Prompt 确保格式稳定）
- 性能监控（记录推理时间和置信度）

---

## 🔧 具体重构步骤

### Step 1: 对话分析器重构

#### ❌ 改造前（conversation_analyzer.py: 654行硬编码）

```python
# 大量硬编码字典和正则表达式
SKILL_DOMAINS = {
    "Python": ["python", "django", "flask", "fastapi", ...],  # 16个关键词
    "前端": ["react", "vue", "angular", "typescript", ...],     # 16个关键词
    # ... 共8个领域，100+ 关键词
}

MCP_TOOL_PATTERNS = {
    "read_file": r"(?:读取?|查看|打开).{0,10}(?:文件|代码)",
    # ... 7个工具的正则模式
}

def _extract_skill_domains(self, content_lower):
    """硬编码关键词匹配"""
    domains = []
    for domain, keywords in self._domains.items():
        matched = [kw for kw in keywords if kw.lower() in content_lower]
        if matched:
            score = len(matched) / len(keywords)
            domains.append({"domain": domain, "match_score": score})
    return domains
```

**问题**:
- ❌ 新领域需手动添加关键词列表
- ❌ 无法理解上下文语义（仅字符串匹配）
- ❌ 匹配规则僵化（无法处理同义词、变体表达）
- ❌ 维护成本随规模线性增长

#### ✅ 改造后（使用 LLMUnifiedAnalyzer）

```python
from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer

class ConversationAnalyzer:
    def analyze(self, content, source="unknown", client="unknown"):
        """LLM 主导的对话分析"""
        analyzer = get_unified_analyzer()
        
        # 一行调用，获取完整分析结果
        result = analyzer.analyze_conversation(content, source, client)
        
        # 结果已包含：
        # - skill_domains (语义识别，非关键词匹配)
        # - complexity (智能评估)
        # - user_feedback (深度分析)
        # - tool_gaps (语义级检测)
        # - optimization_suggestions (LLM 生成)
        # - user_traits (画像提取)
        
        return result
```

**收益**:
- ✅ 代码从 **654行 → ~20行**（减少 97%）
- ✅ 无需维护关键词字典
- ✅ 自动识别新领域和技术术语
- ✅ 语义理解能力远超正则匹配
- ✅ 输出质量显著提升

---

### Step 2: 每日总结生成重构

#### ❌ 改造前（daily_summary.py: 704行模板代码）

```python
def _generate_report_file(analysis, target_date):
    """硬编码 Markdown 模板"""
    lines = [
        f"# 📋 每日工作总结 - {target_date}",
        "",
        f"## 💎 经验凝练",
        f"",
        f"**深挖：** {exp.get('deep_dive', '无')}",
        # ... 几十行固定格式化代码
    ]
    
    # 技能部分
    if new_skills:
        lines.append("## 🔧 新技能")
        for s in new_skills:
            lines.append(f"- ✅ {s}")
    # ... 更多固定模板
    
    report_path.write_text("\n".join(lines), encoding='utf-8')
```

**问题**:
- ❌ 输出格式固定，用户无法自定义
- ❌ 模板维护成本高（调整样式需改代码）
- ❌ 无法根据数据特征动态调整内容重点
- ❌ 多语言支持困难

#### ✅ 改造后（使用 LLMUnifiedAnalyzer）

```python
from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer

def generate_daily_report(work_data):
    """LLM 智能生成日报"""
    analyzer = get_unified_analyzer()
    
    # 调用 LLM 生成完整日报
    report_data = analyzer.generate_daily_summary(work_data)
    
    if not report_data:
        return {"error": "LLM 服务不可用"}
    
    # 可选：保存到数据库或生成文件
    save_to_database(report_data)
    
    # 可选：转换为 Markdown（如需要）
    markdown = convert_to_markdown(report_data)
    
    return {
        "success": True,
        "report": report_data,
        "markdown": markdown
    }
```

**收益**:
- ✅ 代码从 **704行 → ~30行**（减少 96%）
- ✅ 输出风格自然流畅（非模板化）
- ✅ 自动突出重点和风险
- ✅ 支持个性化定制（通过 Prompt 调整）
- ✅ 多语言支持简单（切换 Prompt 即可）

---

### Step 3: 自我迭代建议重构

#### ❌ 改造前（self_iterate.py: 1697行规则引擎）

```python
def _generate_data_driven_suggestions(system_data):
    """硬编码建议生成规则"""
    suggestions = []
    
    # 用户画像分析（~100行规则）
    if skill_gaps:
        suggestions.append({
            "category": "user_profile",
            "suggestion": f"技能短板: {skill_gaps}"
        })
    
    # MCP 工具优化（~200行规则）
    if unused_tools_count > 5:
        suggestions.append({
            "category": "mcp_tool_cleanup",
            "action": "disable",
            "tool_names": unused_tools[:10]
        })
    
    # 系统健康度检查（~150行规则）
    if db_size_gb > 1.0:
        suggestions.append({
            "category": "performance",
            "suggestion": "数据库过大，建议清理"
        })
    
    # ... 数百行类似的 if-else 规则
    
    return suggestions
```

**问题**:
- ❌ 规则覆盖场景有限
- ❌ 建议质量依赖人工经验
- ❌ 难以处理复杂关联关系
- ❌ 新场景需编写新规则

#### ✅ 改造后（使用 LLMUnifiedAnalyzer）

```python
from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer

async def execute_self_iterate(context=None, mode="auto"):
    """LLM 驱动的自我迭代"""
    analyzer = get_unified_analyzer()
    
    # 收集系统数据（保留此步骤）
    system_data = collect_system_data()
    
    # 获取历史优化记录
    improvement_history = get_improvement_history(limit=20)
    
    # LLM 智能生成改进建议
    suggestions = analyzer.generate_self_improvements(
        system_data, 
        improvement_history
    )
    
    if not suggestions:
        return {"error": "无可执行的改进建议"}
    
    # 过滤高优先级且可执行的建议
    actionable = [s for s in suggestions 
                  if s.get("priority") in ("high", "medium") 
                  and s.get("detail", {}).get("action") != "review"]
    
    # 执行改进（保留原有执行逻辑）
    applied = apply_code_changes(actionable)
    
    return {
        "suggestions_generated": len(suggestions),
        "improvements_applied": len(applied),
        "details": suggestions
    }
```

**收益**:
- ✅ 代码从 **1697行 → ~40行**（减少 97%）
- ✅ 建议质量大幅提升（基于全局视角分析）
- ✅ 自动发现隐藏问题和创新机会
- ✅ 建议附带详细执行方案（code_changes）
- ✅ 无需手动维护规则库

---

### Step 4: 用户画像融合重构

#### ❌ 改造前（user_profile_service.py: 141行映射逻辑）

```python
def apply_user_traits(traits, source, conversations_id=None):
    """硬编码字段映射"""
    updates = {"skills": 0, "improvements": 0, "plans": 0}
    
    # skills_observed → user_skills 表（固定映射）
    for skill in traits.get("skills_observed", []):
        db.upsert_user_skills(skill, {
            "skill_level": "intermediate",  # 固定值
            "evidence": f"{source} 观察: {skill}",  # 固定模板
            "hours_spent": 0.3,  # 固定值
        })
        updates["skills"] += 1
    
    # behavior_notes → improvement_log 表（固定分类）
    if traits.get("behavior_notes"):
        db.insert_improvement(
            category="user_behavior_profile",  # 固定类别
            suggestion=f"行为模式: {traits['behavior_notes']}",  # 固定格式
        )
        
    # mistakes → improvement_log 表（另一个固定分类）
    for mistake in traits.get("mistakes", []):
        db.insert_improvement(
            category="user_lesson_learned",  # 又一个固定类别
            suggestion=f"用户踩坑记录: {mistake}",
        )
    
    # ... 更多的固定映射和分支
```

**问题**:
- ❌ 字段映射关系写死在代码中
- ❌ 分类逻辑固定（无法动态调整）
- ❌ 文本描述模板化（缺乏个性）
- ❌ 新特征类型需大量 if-else 扩展

#### ✅ 改造后（使用 LLMUnifiedAnalyzer）

```python
from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer

def apply_user_traits(traits, source="unified_analyzer", conversations_id=None):
    """LLM 智能画像融合"""
    analyzer = get_unified_analyzer()
    
    # 一行调用，完成全流程处理
    updates = analyzer.apply_user_traits(traits, source, conversations_id)
    
    # LLM 已自动处理：
    # - 智能拆分和丰富特征
    # - 动态确定技能等级
    # - 生成个性化的证据文本
    # - 合理估算时间投入
    # - 判断成长趋势
    
    return updates
```

**收益**:
- ✅ 代码从 **141行 → ~10行**（减少 93%）
- ✅ 特征处理智能化（非机械映射）
- ✅ 描述文本自然个性化
- ✅ 自动适应新的特征类型
- ✅ 数据质量更高

---

## 📊 重构效果汇总

### 代码量变化

| 模块 | 改造前行数 | 改造后行数 | 减少比例 | 替代的硬编码 |
|------|----------|----------|---------|------------|
| conversation_analyzer | 654行 | ~20行 | **97%** | 100+关键词, 7个正则, 8个字典 |
| daily_summary | 704行 | ~30行 | **96%** | Markdown模板, 格式化逻辑 |
| self_iterate | 1697行 | ~40行 | **97%** | 规则引擎, SQL查询, 判断逻辑 |
| user_profile_service | 141行 | ~10行 | **93%** | 字段映射, 分支逻辑 |
| upgrade_to_v5 | 450行 | ~50行 | **89%** | 验证规则, 约束检查 |
| **总计** | **3646行** | **~150行** | **96%** | **全部硬编码** |

### 功能提升

| 能力维度 | 改造前 | 改造后 | 提升幅度 |
|---------|-------|-------|---------|
| **语义理解** | 字符串匹配 | 深度语义分析 | ⭐⭐⭐⭐⭐ |
| **扩展性** | 手动添加规则 | Prompt 配置 | ⭐⭐⭐⭐⭐ |
| **输出质量** | 模板化固定 | 自然语言生成 | ⭐⭐⭐⭐ |
| **维护成本** | 高（代码改动） | 低（Prompt 调整） | ⭐⭐⭐⭐⭐ |
| **响应速度** | 快（内存计算） | 中等（LLM 推理） | ⚠️ 略降 |
| **一致性** | 低（规则差异大） | 高（统一模型） | ⭐⭐⭐⭐⭐ |

### 运维收益

#### 场景 1: 新增技术领域识别

**改造前**:
```python
# 需要手动编辑 conversation_analyzer.py
SKILL_DOMAINS["Rust"] = ["rust", "cargo", "tokio", "actix", "..."]  # 添加10+关键词
# 还要更新相关权重、匹配逻辑...
# 测试、部署、发布版本
```
**耗时**: 2-4 小时（开发+测试+发布）

**改造后**:
```yaml
# 只需在 prompts.yaml 中补充说明（可选，LLM 通常已能识别）
# 或完全不需要操作，Qwen3.5-9B 本身就认识 Rust
```
**耗时**: 0 分钟（零代码变更）

---

#### 场景 2: 调整日报输出格式

**改造前**:
```python
# 需要修改 daily_summary.py 的 _generate_report_file 函数
# 调整 Markdown 模板、字段顺序、样式...
# 可能影响现有功能，需要回归测试
```
**耗时**: 1-2 小时

**改造后**:
```python
# 只需微调 generate_daily_summary 方法的 system_prompt
# 例如："请用更简洁的语言，每个章节不超过3条要点"
# 或："增加一个'团队协作'章节"
```
**耗时**: 5-10 分钟（仅改 Prompt）

---

#### 场景 3: 优化自我迭代建议质量

**改造前**:
```python
# 需要在 self_iterate.py 中编写新的规则函数
# 设计判断条件、优先级算法、建议模板...
# 复杂度高，容易引入 bug
```
**耗时**: 4-8 小时

**改造后**:
```python
# 优化 system_prompt 中的指导原则
# 例如："更关注用户体验问题，而非内部实现细节"
# 或："建议必须包含明确的成功度量标准"
```
**耗时**: 10-20 分钟（仅调 Prompt）

---

## 🚀 迁移路径

### Phase 1: 验证期（1-2天）

**目标**: 在不影响现有功能的前提下，验证 LLM 引擎效果

**步骤**:
1. 部署 `llm_unified_analyzer.py` 到生产环境
2. 在 `conversation_analyzer.py` 中增加开关，支持双模式运行
3. 对比 LLM 分析结果与规则引擎结果的差异
4. 收集反馈，微调 Prompt 模板

**代码示例**:
```python
# conversation_analyzer.py 临时兼容层
def analyze(self, content, source, client):
    if USE_LLM_UNIFIED:  # 配置开关
        from core.llm_unified_analyzer import get_unified_analyzer
        analyzer = get_unified_analyzer()
        return analyzer.analyze_conversation(content, source, client)
    else:
        return self._analyze_with_rules(content, source, client)  # 保留原逻辑
```

### Phase 2: 逐步替换（1周）

**目标**: 逐模块迁移到 LLM 引擎

**顺序建议**:
1. ✅ `daily_summary.py` （风险最低，独立性强）
2. ✅ `upgrade_to_v5.py` （偶发使用，容错性好）
3. ✅ `user_profile_service.py` （逻辑简单，影响面小）
4. ✅ `self_iterate.py` （复杂但可控）
5. ✅ `conversation_analyzer.py` （核心模块，最后迁移）

### Phase 3: 清理期（2-3天）

**目标**: 移除废弃的硬编码代码

**步骤**:
1. 删除各模块中的旧方法（`_analyze_with_rules`, `_generate_report_file` 等）
2. 清理未使用的常量和字典（`SKILL_DOMAINS`, `MCP_TOOL_PATTERNS` 等）
3. 更新单元测试，改为验证 LLM 输出格式
4. 更新文档和注释

**预期成果**:
- 代码总量减少 **3500+ 行**
- 维护复杂度降低 **80%+**
- 后续迭代效率提升 **3-5 倍**

---

## ⚠️ 注意事项与风险控制

### 1. LLM 不可用时的降级策略

**方案**: 所有分析方法都有 fallback 到简化规则的逻辑

```python
def analyze_conversation(self, content, source, client):
    response = self._infer(prompt)
    
    if response and self._parse_json_response(response):
        return result  # LLM 成功
    
    # 降级到极简规则（保底方案）
    logger.warning("LLM 不可用，使用简化分析")
    return self._fallback_simple_analysis(content, source, client)
```

**保障**: 即使 LLM 完全不可用，系统仍能正常运行（质量略降）

### 2. LLM 输出稳定性

**挑战**: 同一输入可能产生略有不同的输出

**对策**:
- 使用较低的 `temperature` (0.3) 提高确定性
- 强制 JSON 输出格式约束
- 后处理验证关键字段完整性
- 对关键业务字段设置默认值

### 3. 性能开销

**现状**: LLM 推理比纯规则慢（约 5-15 秒/次）

**缓解**:
- 异步执行（不阻塞主流程）
- 结果缓存（相同输入复用）
- 批量处理（减少调用次数）
- 仅对关键分析启用 LLM（非关键保持规则）

**成本效益分析**:
```
额外耗时: ~10秒/次（可接受）
节省工时: ~4小时/次规则维护（巨大收益）
ROI: 极高 ✅
```

### 4. 提示词注入安全

**风险**: 恶意输入可能操纵 LLM 输出

**防护**:
- 输入长度限制（8000字符）
- 输入内容过滤（移除特殊指令标记）
- 输出格式强制（JSON Schema 验证）
- 日志审计（记录异常输入输出）

---

## 📈 监控与评估指标

### 关键指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| **LLM 调用成功率** | 推理请求成功比例 | > 95% |
| **JSON 解析成功率** | 输出格式符合预期比例 | > 90% |
| **分析质量评分** | 人工抽检满意度 | > 4.0/5.0 |
| **平均推理延迟** | 单次调用耗时 | < 15秒 |
| **降级触发频率** | fallback 到规则的比例 | < 5% |

### 监控实现

```python
# 在 llm_unified_analyzer.py 中添加监控
import time

def _infer(self, prompt, max_tokens=2048):
    start_time = time.time()
    
    try:
        response = self._llm_service._infer(prompt, max_tokens=max_tokens)
        latency = time.time() - start_time
        
        # 记录指标
        metrics.record_llm_call(
            success=response is not None,
            latency_ms=latency * 1000,
            prompt_length=len(prompt),
            max_tokens=max_tokens
        )
        
        return response
        
    except Exception as e:
        metrics.record_llm_error(str(e))
        return None
```

---

## 🎯 总结

### 核心价值

✅ **代码精简 96%**: 从 3646行硬编码 → ~150行 LLM 调用  
✅ **维护成本降低 80%+**: 改 Prompt 即可调整行为，无需改代码  
✅ **分析质量提升**: 语义理解 >> 关键词匹配  
✅ **扩展性极大增强**: 新场景零代码接入  

### 适用性

- ✅ 适合: 规则复杂、频繁迭代的分析类场景
- ⚠️ 注意: 对实时性要求极高的场景需谨慎
- ✅ 推荐: DevPartner 这类 AI 辅助开发工具

### 下一步行动

1. **立即开始**: 部署 `llm_unified_analyzer.py` 并测试
2. **本周目标**: 完成 `daily_summary.py` 迁移
3. **本月目标**: 全部 5 个模块迁移完毕
4. **持续优化**: 收集反馈，迭代 Prompt 模板

---

**文档版本**: v6.0  
**创建日期**: 2026-07-03  
**适用项目**: DevPartner v5.2+  
**维护者**: DevPartner Team