# LLM 分析管线系统级优化报告

> 日期: 2026-07-23 | 版本: v9.11 | 范围: 全系统 17 个分析任务

## 概览

对 devPartner 全部 LLM 分析管线进行了 3 维度诊断与代码级优化：
1. **数据精简** — 删除冗余字段、补充缺失数据
2. **分析维度审视** — 删除幻觉维度、合并重叠维度
3. **报告生成优化** — 收紧输入截断、减少输出 token、增强反幻觉约束

---

## 优化矩阵

| # | 任务 | 优先级 | 维度 | 问题 | 修复 | Token 节省 |
|---|------|--------|------|------|------|-----------|
| 1 | TASK_BEHAVIOR_SIGNALS | P0 | 数据+维度 | 7 个输出字段全是关键词/正则匹配（has_code_block, input_length 等），浪费一次 LLM round-trip | **删除 LLM task，改为 `_common.py` 中 `extract_behavior_signals()` Python 函数** | **100%（消除整个 LLM 调用）** |
| 2 | TASK_USER_PROFILE_ANALYSIS | P0 | 数据 | 每次注入 ~1500-2000 token 静态块（USER_TRAITS_SCHEMA + FEW_SHOT_EXAMPLES + PROJECT_STRATEGY + ANALYSIS_GUIDELINES），其中 FEW_SHOT 示例是泛型 React/Django/Docker | **压缩为 `_COMPACT_PROFILE_REF` 精简参考卡，内联到 prompt_template** | **~60%（约 1200 token/call）** |
| 3 | TASK_STEP_ANALYSIS | P1 | 维度 | 输出 12+ 字段：`dead_ends`/`prerequisites`/`related_patterns` 常被虚构；`related_tools` 与 `skill_domains` 重叠；`thinking_patterns`+`complexity_level` 与 `difficulty` 三重重叠；`ai_reasoning` 输入与 `content` 重叠 | **删除 6 个输出字段（dead_ends, prerequisites, related_patterns, related_tools, thinking_patterns, complexity_level）；删除 ai_interpretation 输出；删除 ai_reasoning 输入字段；max_tokens 4096→3000** | **~40%（约 800 output token/call + 约 500 input token/call）** |
| 4 | TASK_CONVERSATION_ANALYSIS | P1 | 维度 | `user_traits` 9 维度与 TASK_CONV_USER_PROFILE 高度重叠，两次 LLM 调用提取同一信息 | **从 CONVERSATION_ANALYSIS 中移除 user_traits 和 tool_gaps（LLM 不知工具目录）；max_tokens 2048→1500** | **~30%（约 600 output token/call + 消除重复分析）** |
| 5 | TASK_BUSINESS_TECH_ASSESSMENT | P1 | 数据 | `input_truncate=24000` 过大；`ai_analysis[:10000]`+`user_raw_input[:5000]`+`summary`+`key_decisions` 重叠严重；`psychological_notes` 输出高幻觉风险 | **input_truncate 24000→12000；合并 summary+key_decisions 为 compact_context；收紧截断（project_context[:1500], user_raw_input[:3000], ai_analysis[:5000]）；删除 psychological_notes；max_tokens 4096→3000** | **~50% input + ~25% output** |
| 6 | TASK_CONV_USER_PROFILE | P1 | 数据 | 同上，`input_truncate=24000` 过大；`user_raw_input[:5000]`+`ai_analysis[:10000]` 合计 15000 字符超出 7B 模型有效注意力 | **input_truncate 24000→12000；收紧截断（user_raw_input[:3000], ai_analysis[:5000]）；删除 psychological_notes；max_tokens 3072→2000** | **~50% input + ~35% output** |
| 7 | TASK_KNOWLEDGE_EXTRACTION | P2 | 数据 | `existing_titles_list` 无上限增长（token bomb）；domain 归类规则与 user_profile 重复（各 7 个领域 × 2 处 = 14 段描述） | **existing_titles_list 限制最多 200 条；domain 规则精简为一行"必须从标准领域选择"而非逐条列举** | **~20-80%（取决于已有知识量）** |
| 8 | TASK_USER_TRAITS_ENRICH | P2 | 维度 | `estimated_hours`（LLM 无法估算学习时间）和 `growth_trend`（纯推测）两个输出字段 | **删除这 2 个 LLM 输出字段，改为 Python 确定性计算（首次 0.3h + growing）；max_tokens 1024→512** | **~50% output** |
| 9 | TASK_BATCH_STEP_ANALYSIS | P2 | 维度 | prompt 缺少 JSON 输出 schema 示例，LLM 输出格式不稳定 | **暂保留（改动风险低，后续补 schema）** | — |

---

## 具体代码变更清单

### 新增文件
- `backend/templates/llm_prompt/_common.py`: 新增 `extract_behavior_signals()` 函数（100 行）

### 修改文件

| 文件 | 变更摘要 |
|------|----------|
| `backend/templates/llm_prompt/user_profile.py` | 删除 TASK_BEHAVIOR_SIGNALS + 4 静态块 → 替换为 _COMPACT_PROFILE_REF 内联到 prompt |
| `backend/templates/llm_prompt/step.py` | 删除 6 输出字段 + ai_reasoning 输入；max_tokens 4096→3000 |
| `backend/templates/llm_prompt/conversation.py` | 移除 user_traits + tool_gaps；max_tokens 2048→1500 |
| `backend/templates/llm_prompt/deep_analysis.py` | business_tech: 删 psychological_notes, 合并 compact_context, input 24000→12000, 截断收紧; user_profile: 删 psychological_notes, input 24000→12000, 截断收紧 |
| `backend/templates/llm_prompt/knowledge_extraction.py` | domain 规则精简；existing_titles 上限提示 |
| `backend/templates/llm_prompt/auxiliary.py` | 删 estimated_hours/growth_trend; max_tokens 1024→512 |
| `backend/templates/llm_prompt/__init__.py` | 导出更新（删旧静态块引用，加 extract_behavior_signals） |
| `backend/core/llm_kernel/base_client.py` | analyze_step_content 删 ai_reasoning 参数; _prepare_business_tech_kwargs 合并 compact_context + 截断收紧; _prepare_user_profile_kwargs 截断收紧; apply_user_traits 改为 Python 计算 estimated_hours/growth_trend |
| `backend/core/task_recovery.py` | 删除 behavior_signals_extraction 去重/依赖配置 |
| `backend/business/knowledge_extractor/extract_service.py` | existing_titles 限制最多 200 条 |

---

## 总体效果估算

| 指标 | 优化前 | 优化后 | 节省 |
|------|--------|--------|------|
| TASK_BEHAVIOR_SIGNALS | 1 LLM call + ~400 input token + ~150 output token | 0（Python 函数） | **100%** |
| TASK_USER_PROFILE_ANALYSIS input | ~1500-2000 静态块 + dynamic | ~300 静态 + dynamic | **~60% static** |
| TASK_STEP_ANALYSIS output | ~3000-4000 token | ~1800-2500 token | **~30-40%** |
| TASK_CONVERSATION_ANALYSIS output | ~1500-2000 token | ~800-1200 token | **~30-40%** |
| TASK_BUSINESS_TECH_ASSESSMENT input | ~20000-24000 char | ~10000-12000 char | **~50%** |
| TASK_BUSINESS_TECH_ASSESSMENT output | ~3000-4000 token | ~2000-2800 token | **~25-30%** |
| TASK_CONV_USER_PROFILE input | ~15000-24000 char | ~8000-12000 char | **~50%** |
| TASK_KNOWLEDGE_EXTRACTION existing_titles | 无上限 | 最多 200 条 | **潜在 80%+** |
| TASK_USER_TRAITS_ENRICH output | ~800-1024 token | ~300-512 token | **~50%** |

**粗估每日总 token 节省（按日均 50 次分析调用）**：~30,000-50,000 token/day
**粗估每日总执行时间节省**：每次 BEHAVIOR_SIGNALS 替换省 ~3-10s LLM 调用；其他优化省 10-30% 推理时间

---

## 反幻觉措施汇总

| 措施 | 作用位置 |
|------|----------|
| 删除 `dead_ends`/`prerequisites`/`related_patterns` 输出字段 | STEP_ANALYSIS |
| 删除 `psychological_notes` 输出字段 | BUSINESS_TECH_ASSESSMENT + CONV_USER_PROFILE |
| 删除 `tool_gaps` 输出字段 | CONVERSATION_ANALYSIS（LLM 不知工具目录） |
| 删除 `estimated_hours`/`growth_trend` 输出字段 | USER_TRAITS_ENRICH（改为 Python 确定性计算） |
| 新增"不确定的字段不虚构"约束 | STEP_ANALYSIS 提纯原则 #5 |
| 新增 `extract_behavior_signals()` Python 替代 | 完全消除 LLM 对简单模式匹配的"幻觉" |

---

## 未改动任务（评估为无需优化）

| 任务 | 评估 |
|------|------|
| TASK_DAILY_SUMMARY | P1 已增强（facts/psychology/metrics with evidence），无需再改 |
| TASK_WEEKLY/MONTHLY/ANNUAL/GROWTH_REPORT | P0 已修复（4 prompt 补回），已有 facts/psychology 结构 |
| TASK_SELF_IMPROVEMENT | 相对干净，改动风险高 |
| TASK_FILE_PARSE | 标准、干净 |
| TASK_SCHEMA_ANALYSIS | 标准、干净 |
| TASK_REVIEW_PROJECT_DESC | 最小 prompt，max_tokens=256 |
| TASK_QUESTION_EXPAND | 最小 prompt，max_tokens=256 |

---

## 后续建议

1. **TASK_BATCH_STEP_ANALYSIS**: 补充 JSON 输出 schema 示例（当前 LLM 输出格式不稳定）
2. **TASK_CONVERSATION_ANALYSIS**: 如果需要 tool_gaps，改为基于 `get_rules()` 工具目录的确定性匹配（Python 代码），而非让 LLM 猜测
3. **监控指标**: 在 dashboard 添加 `token_usage_per_task` 统计，量化每次 LLM 调用的 token 消耗
4. **定期审计**: 每 3 个月重复此审计流程，检查是否有新引入的冗余维度
