# DevPartner v5.0 数据库升级工具 - LLM 驱动版

## 📋 概述

本脚本已从**硬编码逻辑**升级为 **LLM 驱动架构**，依托本地 `llama-cpp-python` + Qwen3.5-9B 模型承载全流程数据分析与结果归纳工作。

## 🎯 核心改进

### ✅ 摒弃硬编码
- ❌ ~~固定规则判断表是否存在~~
- ❌ ~~硬编码字段名和约束检查~~
- ❌ ~~手动拼接验证逻辑~~

### ✅ LLM 统一提示词体系
- 🤖 **Schema 分析**：LLM 动态识别数据库结构和问题
- 🔍 **智能验证**：对比升级前后快照，自动评估数据完整性
- 📊 **报告生成**：结构化 Markdown 迁移报告，包含风险评估和建议
- 💡 **自适应策略**：根据实际数据特征动态调整分析深度

## 🛠️ 技术栈

| 组件 | 版本/规格 |
|------|----------|
| 推理引擎 | llama-cpp-python ≥0.2.79 |
| 模型 | Qwen3.5-9B-Q4_1 (GGUF, ~5.7GB) |
| 配置 | config.yaml 统一管理 |
| 降级方案 | traditional_upgrader.py |

## 📖 使用方法

### 基本用法（推荐）
```bash
# 使用 LLM 驱动模式（自动检测并加载模型）
python scripts/upgrade_to_v5.py
```

### 传统模式（回退）
```bash
# 当 LLM 服务不可用时，使用硬编码逻辑
python scripts/upgrade_to_v5.py --no-llm
```

## 🔄 执行流程

```
Step 1: 备份数据库 → 自动创建带时间戳的备份文件
Step 2: 连接数据库 → 收集当前 Schema 元信息
Step 3: LLM 分析诊断 → 识别问题、评估风险、生成建议
Step 4: 执行升级 + 验证 → SQL 执行 → LLM 验证 → 生成报告
```

## 📊 输出示例

### LLM 分析阶段输出示例：
```
Step 3/4: LLM 智能分析当前 Schema...
   📈 数据质量评分: 0.85
   🔍 发现问题: 3 个

   ⚠️ 主要问题:
      1. 🔴 [conversations] 缺少 conversation_id 唯一约束
      2. 🟡 [knowledge_points] created_at 字段缺失
      3. 🟢 [task_queue] 索引未优化

   💡 LLM 建议:
      → 建议在升级前手动备份关键表数据
      → 升级后立即运行完整性校验
```

### 最终验证输出示例：
```
🔍 LLM 验证结果:
   状态: success
   置信度: 92.5%
   新建表: ['conversation_steps', 'knowledge_points', 'task_queue']

📊 LLM 生成的迁移报告:
============================================================
# DevPartner v5.0 数据库升级迁移报告

## 📋 执行摘要
✅ 升级成功完成，所有 v5.0 Schema 要求均已满足...
============================================================
```

## ⚙️ 配置要求

### 必需配置（config.yaml）：
```yaml
llm:
  enabled: true
  model_path: "D:/WorkSpace/AI_model/Qwen3.5-9B-Q4_1.gguf"
  n_ctx: 8192          # 上下文长度
  n_gpu_layers: -1     # GPU 加速（-1=全部）
  n_threads: 8         # CPU 线程数
  max_tokens: 2048     # 最大生成长度
  temperature: 0.3     # 生成温度
```

### 依赖安装：
```bash
# 基础版本（CPU 推理）
pip install llama-cpp-python>=0.2.79

# GPU 加速版本（CUDA 12.1）
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

## 🔧 故障排查

### 问题 1: LLM 服务不可用
**症状**: `⚠️ LLM 服务不可用`

**解决方案**:
1. 检查模型文件路径是否正确
2. 确认 llama-cpp-python 已安装
3. 使用 `--no-llm` 参数回退到传统模式

### 问题 2: LLM 返回格式异常
**症状**: `⚠️ LLM 返回格式异常`

**原因**: Qwen3.5-9B 未严格遵循 JSON 格式要求

**处理**: 脚本会自动降级到原始响应模式，不影响升级流程

### 问题 3: 推理速度慢
**建议**:
- 启用 GPU 加速: `n_gpu_layers: -1`
- 减少上下文长度: `n_ctx: 4096`
- 增加 CPU 线程数: `n_threads: 16`

## 📈 性能指标

基于 Qwen3.5-9B-Q4_1 的测试结果：

| 操作 | 耗时 | Token 消耗 |
|------|------|-----------|
| Schema 分析 | ~8-15秒 | ~1200 tokens |
| 升级验证 | ~10-20秒 | ~1500 tokens |
| 报告生成 | ~15-25秒 | ~2500 tokens |
| **总计** | **~35-60秒** | **~5200 tokens** |

## 🎯 适用场景

### ✅ 推荐 LLM 模式
- 生产环境首次升级
- 需要详细审计日志的场景
- 数据库结构复杂的系统
- 需要风险评估和回滚建议

### ✅ 可用传统模式
- 开发环境快速迭代
- LLM 服务临时不可用
- 已知数据库结构简单的情况

## 📝 注意事项

1. **备份优先**: 脚本会自动备份，但建议手动确认备份文件完整性
2. **监控资源**: LLM 推理期间内存占用约 6GB+（含模型）
3. **网络无关**: 本地推理，无需互联网连接
4. **可重复执行**: 幂等设计，多次运行不会导致数据损坏

## 🔗 相关文件

- [upgrade_to_v5.py](./upgrade_to_v5.py) - 主脚本（LLM 驱动版）
- [traditional_upgrader.py](./traditional_upgrader.py) - 传统模式回退模块
- [v5.0_schema_upgrade.sql](./v5.0_schema_upgrade.sql) - SQL 升级脚本
- [../devpartner_agent/config.yaml](../devpartner_agent/config.yaml) - LLM 配置文件

---

**最后更新**: 2026-07-03  
**适用版本**: DevPartner v5.0+  
**维护者**: DevPartner Team