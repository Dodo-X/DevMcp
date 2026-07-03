# 测试套件

本目录包含 DevPartner 项目的所有测试代码。

## 📁 测试文件说明

| 测试文件 | 说明 | 覆盖范围 |
|---------|------|---------|
| `test_v5_core.py` | v5.0 核心功能测试 | 数据库 Schema、知识图谱、任务队列 |
| `test_llm_analyzer.py` | LLM 引擎测试 | 对话分析、日报生成、自我改进 |
| `test_integration.py` | 集成测试 | 端到端流程验证 |
| `test_performance.py` | 性能基准测试 | 推理速度、内存占用、并发能力 |

## 🚀 运行测试

### 运行全部测试
```bash
# 从项目根目录执行
pytest tests/ -v

# 或使用详细输出
pytest tests/ -v --tb=short
```

### 运行特定测试
```bash
# 仅运行 LLM 相关测试
pytest tests/test_llm_analyzer.py -v

# 运行核心功能测试
pytest tests/test_v5_core.py -v
```

### 生成覆盖率报告
```bash
pytest tests/ --cov=devpartner_agent --cov-report=html
```

报告将生成在 `htmlcov/index.html`

## 📊 测试分类

### 单元测试 (Unit Tests)
- **目标**: 验证单个函数/方法的正确性
- **特点**: 快速（<1秒）、独立、可重复
- **示例**: 测试 LLM 输出解析、数据库 CRUD 操作

### 集成测试 (Integration Tests)
- **目标**: 验证模块间协作的正确性
- **特点**: 中等速度（1-10秒）、依赖外部服务
- **示例**: 对话记录→分析→存储完整流程

### 性能测试 (Performance Tests)
- **目标**: 验系统性能指标达标
- **特点**: 慢速（>10秒）、需要基线数据
- **示例**: LLM 推理延迟、并发处理能力

## ✅ 测试要求

### 新增代码必须包含测试
- 核心业务逻辑: 覆盖率 ≥ 80%
- 工具函数: 覆盖率 ≥ 90%
- 关键路径: 必须有边界条件测试

### 测试命名规范
```python
def test_[module]_[function]_[scenario]():
    """
    示例:
    - test_llm_analyzer_conversation_success()
    - test_database_insert_duplicate_key()
    - test_conversation_analyzer_empty_input()
    """
    pass
```

## 🔧 测试配置

### pytest.ini (项目根目录)
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
addopts = -v --tb=short
```

### 环境变量
```bash
# 测试环境标记
export TEST_ENV=true

# LLM 测试模式（跳过实际推理）
export LLM_TEST_MODE=mock

# 数据库测试（使用内存数据库）
export TEST_DB=:memory:
```

## 🐛 常见问题

### Q1: LLM 测试太慢？
**A**: 使用 mock 模式：
```python
@pytest.mark.llm_mock
def test_analyzer_with_mock():
    # 不调用真实 LLM，使用预设响应
    pass
```

### Q2: 数据库测试污染生产数据？
**A**: 测试自动使用临时数据库：
```python
@pytest.fixture(scope="function")
def db_session():
    # 每个测试用独立的内存数据库
    yield create_test_db(":memory:")
```

### Q3: 如何调试失败测试？
```bash
# 显示完整堆栈
pytest tests/test_xxx.py -v --tb=long

# 进入 pdb 调试器
pytest tests/test_xxx.py --pdb

# 只运行失败的测试
pytest tests/ --lf
```

## 📈 测试统计

最近一次测试运行结果（2026-07-03）:
- 总测试数: 42
- 通过: 40 (95.2%)
- 失败: 2 (4.8%)
- 跳过: 0
- 总耗时: 127.5 秒
- 覆盖率: 78.3%

---

**维护者**: DevPartner QA Team  
**最后更新**: 2026-07-03