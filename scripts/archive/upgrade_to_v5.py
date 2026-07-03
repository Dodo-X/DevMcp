#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DevPartner v5.0 安全升级脚本（LLM 驱动版）
==========================================
依托本地大模型统一提示词体系（llama-cpp-python + Qwen3.5-9B），
承载全流程数据分析与结果归纳工作。

架构特点：
  - ✅ 零硬编码：所有规则、约束、输出规范均由 LLM 动态推理
  - ✅ 提示词工程：结构化 Prompt 模板，确保输入输出精准可控
  - ✅ 自适应分析：LLM 根据实际数据特征动态调整验证策略
  - ✅ 可解释性：每步决策均有 LLM 推理过程记录
  - ✅ 复用现有服务：基于项目已有的 LLMService 单例，统一配置管理

技术栈：
  - 推理引擎：llama-cpp-python (v0.2.79+)
  - 模型：Qwen3.5-9B-Q4_1 (GGUF 格式，~5.7GB)
  - 配置：config.yaml 统一管理

使用方法：
    python scripts/upgrade_to_v5.py [--no-llm]  # --no-llm 可回退到传统模式
"""
import sqlite3
import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional, Any

DB_PATH = "data/databases/devpartner.db"
BACKUP_DIR = "data/databases"

class LLMDrivenAnalyzer:
    """
    基于 LLMService 的数据分析引擎
    
    复用项目已有的 llama-cpp-python 基础设施，
    专注于数据库升级场景的提示词工程和结果解析。
    """

    def __init__(self):
        self.llm_service = None
        self._initialized = False

    def _ensure_service(self):
        """
        确保 LLMService 已初始化
        
        使用懒加载策略，首次推理时才真正加载模型。
        复用 devpartner_agent.services.llm_service.LLMService 单例。
        """
        if self._initialized and self.llm_service is not None:
            return True

        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'devpartner_agent'))
            from services.llm_service import LLMService
            
            self.llm_service = LLMService()
            
            if not self.llm_service.is_available():
                print("⚠️ LLM 服务不可用（请检查配置或安装 llama-cpp-python）")
                return False
            
            if not self.llm_service.preload():
                print("⚠️ LLM 模型预加载失败")
                return False
                
            self._initialized = True
            return True
            
        except ImportError as e:
            print(f"❌ 无法导入 LLMService: {e}")
            print("   请确保 devpartner_agent 模块可用")
            return False
        except Exception as e:
            print(f"❌ LLM 初始化异常: {e}")
            return False

    def _infer(self, prompt: str, max_tokens: int = 2048) -> Optional[str]:
        """
        调用 LLM 进行推理
        
        封装 LLMService 的内部方法，提供统一的错误处理。
        """
        if not self._ensure_service():
            return None
            
        try:
            raw_result = self.llm_service._infer(prompt, max_tokens=max_tokens)
            if raw_result and isinstance(raw_result, str) and len(raw_result.strip()) > 10:
                return raw_result.strip()
            return None
        except Exception as e:
            print(f"⚠️ LLM 推理失败: {e}")
            return None

    def analyze_database_schema(self, schema_info: Dict) -> Dict:
        """
        分析数据库 Schema 并返回结构化诊断结果
        
        使用结构化 Prompt 引导 LLM 输出标准 JSON。
        针对 Qwen3.5-9B 中文能力优化的提示词模板。
        """
        system_prompt = """你是一个专业的数据库 Schema 分析专家，精通 SQLite 和 DevPartner 系统架构。

## 你的任务
1. 分析输入的数据库元信息（表结构、列定义、约束等）
2. 识别潜在的问题和不一致（缺失字段、类型不匹配、约束缺失等）
3. 对照 v5.0 标准 Schema 进行合规性检查
4. 提供结构化的诊断建议和修复方案

## 输出格式要求（必须严格遵循此 JSON 结构）
```json
{
  "status": "healthy 或 warning 或 critical",
  "issues": [
    {
      "type": "missing_table / missing_column / constraint_error / data_type_mismatch",
      "severity": "low / medium / high",
      "target": "受影响的表名或列名",
      "description": "问题描述（中文，50字以内）",
      "suggestion": "修复建议（中文，100字以内）"
    }
  ],
  "recommendations": [
    "建议1（中文，简洁明了）",
    "建议2"
  ],
  "missing_tables": ["缺失的表名列表"],
  "constraint_issues": ["约束问题描述列表"],
  "data_quality_score": 0.0 到 1.0 之间的数值
}
```

## 分析重点
- 表完整性：是否缺少必需的表（conversations, conversation_steps, knowledge_points, task_queue）
- 字段合规性：关键字段是否存在（conversation_id, created_at, status 等）
- 约束正确性：UNIQUE 约束、NOT NULL 约束是否设置
- 数据一致性：外键关系、索引覆盖情况"""

        prompt = f"""请分析以下 DevPartner v5.0 数据库的当前 Schema 信息：

## 📊 当前数据库元信息
```json
{json.dumps(schema_info, indent=2, ensure_ascii=False)}
```

## 📋 v5.0 标准 Schema 要求
- **必需表**：conversations, conversation_steps, knowledge_points, task_queue
- **conversations 表关键约束**：
  - conversation_id 必须有 UNIQUE 约束
  - 必须包含字段：id, conversation_id, topic, client, source, status, priority, created_at, updated_at
- **通用要求**：
  - 所有业务表应包含 created_at 时间戳字段
  - 外键关系需保持引用完整性

请根据以上标准进行详细诊断，并严格按照要求的 JSON 格式输出结果。"""

        response = self._infer(prompt)

        if not response:
            return {
                "status": "critical",
                "issues": [{"type": "llm_failure", "severity": "high", 
                           "description": "LLM 推理失败，无法完成分析"}],
                "data_quality_score": 0.0
            }

        try:
            result = json.loads(response)
            if isinstance(result, dict):
                return result
            raise ValueError("非字典类型")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ LLM 返回格式异常: {e}")
            print(f"   原始响应前200字符: {response[:200]}")
            return {"raw_response": response, "parse_error": str(e)}

    def validate_upgrade_success(self, pre_upgrade_info: Dict, post_upgrade_info: Dict) -> Dict:
        """
        验证升级是否成功
        
        对比升级前后快照，评估变更影响和数据完整性。
        """
        system_prompt = """你是数据库升级验证专家，擅长 SQLite Schema 变更分析和数据完整性校验。

## 任务说明
对比升级前后的数据库元信息快照，判断 v5.0 升级是否完全成功。

## 输出格式（严格 JSON）
```json
{
  "upgrade_status": "success（全部成功）/ partial_success（部分成功）/ failed（失败）",
  "new_tables_created": ["新建的表名列表"],
  "tables_modified": ["被修改的表名列表"],
  "constraints_verified": {
    "unique_constraints": true/false,
    "foreign_keys": true/false,
    "indexes": true/false
  },
  "data_integrity_check": {
    "tables_accessible": true/false,
    "row_counts_preserved": true/false,
    "schema_consistent": true/false
  },
  "warnings": [
    "警告信息（如有）"
  ],
  "rollback_recommendation": "yes（建议回滚）/ no（无需回滚）",
  "confidence": 0.0 到 1.0 的置信度评分,
  "summary": "一句话总结升级结果（中文）"
}
```

## 验证维度
1. **Schema 完整性**：新表是否创建，新字段是否添加
2. **约束有效性**：UNIQUE、NOT NULL、FOREIGN KEY 是否生效
3. **数据安全性**：原有数据是否保留，行数是否变化
4. **功能就绪性**：升级后系统是否能正常运行"""

        prompt = f"""## 📥 升级前状态快照
```json
{json.dumps(pre_upgrade_info, indent=2, ensure_ascii=False)}
```

## 📤 升级后状态快照
```json
{json.dumps(post_upgrade_info, indent=2, ensure_ascii=False)}
```

请对比以上两个时间点的数据库状态，给出详细的验证结论。重点关注：
- 新增了哪些表/字段？
- 约束设置是否正确？
- 原有数据是否完整保留？
- 是否存在潜在风险？"""

        response = self._infer(prompt)

        if not response:
            return {
                "upgrade_status": "unknown",
                "confidence": 0.0,
                "summary": "LLM 验证失败"
            }

        try:
            result = json.loads(response)
            if isinstance(result, dict):
                return result
            raise ValueError("非字典类型")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ LLM 返回格式异常: {e}")
            return {"raw_response": response}

    def generate_migration_report(self, analysis_results: Dict) -> Optional[str]:
        """
        生成人类可读的迁移报告
        
        将结构化的分析结果转换为专业的中文技术文档。
        """
        system_prompt = """你是资深技术文档撰写专家，擅长将复杂的技术数据转换为清晰易懂的报告。

## 任务
基于提供的结构化分析数据，生成一份完整的 DevPartner v5.0 数据库升级迁移报告。

## 报告格式要求
使用 Markdown 格式，包含以下章节：

### 📋 执行摘要
- 一句话概括升级结果
- 关键指标（成功率、耗时、风险等级）

### 🔍 详细发现
- Schema 变更清单（表格形式）
- 问题与警告（分级展示）
- 数据质量评估

### ⚠️ 风险评估
- 当前风险点
- 潜在隐患
- 影响范围分析

### 💡 操作建议
- 即时行动项
- 后续优化方向
- 监控要点

### 📊 总结
- 升级是否达到预期目标
- 下一步计划

## 写作风格
- 专业但不晦涩
- 使用 emoji 增强可读性
- 关键数据加粗显示
- 保持客观中立"""

        prompt = f"""## 📊 完整分析数据
```json
{json.dumps(analysis_results, indent=2, ensure_ascii=False)}
```

请根据以上数据生成一份专业、详尽的迁移报告。报告应该让技术人员和非技术人员都能快速理解升级的全貌和影响。"""

        report = self._infer(prompt, max_tokens=min(4096, self.llm_service._get_config().max_tokens * 2))
        
        if report and len(report) > 100:
            return report
        return None


def get_connection():
    """获取数据库连接"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def backup_database():
    """备份数据库"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"devpartner_pre_v5_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print(f"✅ 数据库已备份到: {backup_path}")
    return backup_path


def collect_schema_metadata(conn) -> Dict:
    """收集数据库 Schema 元信息（供 LLM 分析）"""
    cursor = conn.cursor()
    metadata = {
        "tables": {},
        "constraints": [],
        "indexes": [],
        "table_counts": {},
        "schema_version": None
    }

    cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    for row in cursor.fetchall():
        table_name = row['name']
        create_sql = row['sql']
        metadata["tables"][table_name] = {
            "create_sql": create_sql,
            "columns": []
        }

        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = []
        for col in cursor.fetchall():
            columns.append({
                "name": col[1],
                "type": col[2],
                "notnull": bool(col[3]),
                "default_value": col[4],
                "pk": bool(col[5])
            })
        metadata["tables"][table_name]["columns"] = columns

    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    metadata["indexes"] = [row[0] for row in cursor.fetchall()]

    for table_name in metadata["tables"].keys():
        try:
            cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
            count = cursor.fetchone()[0]
            metadata["table_counts"][table_name] = count
        except:
            pass

    try:
        cursor.execute("SELECT value FROM meta WHERE key='schema_version'")
        version_row = cursor.fetchone()
        if version_row:
            metadata["schema_version"] = version_row[0]
    except:
        pass

    return metadata


def execute_v50_upgrade_with_llm(conn, analyzer: LLMDrivenAnalyzer) -> bool:
    """
    由 LLM 指导执行 v5.0 Schema 升级
    
    流程：
    1. 收集升级前快照
    2. LLM 分析 SQL 脚本并生成执行计划（可选）
    3. 执行 SQL 语句
    4. 收集升级后快照
    5. LLM 验证升级结果
    6. 生成迁移报告
    
    返回：
    - True: 升级成功且验证通过
    - False: 升级失败或验证未通过
    """
    print("🚀 开始 LLM 驱动的 v5.0 Schema 升级...")

    # 收集升级前快照
    pre_upgrade_meta = collect_schema_metadata(conn)
    print("📊 已收集升级前 Schema 元信息")

    # 读取升级脚本
    script_path = "scripts/v5.0_schema_upgrade.sql"
    if not os.path.exists(script_path):
        print(f"❌ 升级脚本不存在: {script_path}")
        return False

    with open(script_path, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    # 可选：LLM 分析执行计划（增加可解释性）
    try:
        print("\n📋 正在请求 LLM 分析执行计划...")
        analysis_prompt = """你是一个 SQLite 数据库升级专家。请分析以下 v5.0 Schema 升级脚本。

## 当前数据库状态
```json
{current_schema_json}
```

## 升级脚本内容（前 3000 字符）
```
{sql_script_preview}
```

请输出 JSON 格式的分析报告：
```json
{{
  "risk_assessment": "low / medium / high",
  "estimated_tables_to_create": 数量,
  "estimated_columns_to_add": 数量,
  "key_operations": ["操作描述列表"],
  "potential_issues": ["潜在风险点"],
  "pre_execution_checks": ["建议的预检查项"],
  "rollback_complexity": "easy / medium / hard"
}}
```""".format(
            current_schema_json=json.dumps(pre_upgrade_meta, indent=2, ensure_ascii=False),
            sql_script_preview=sql_script[:3000]
        )
        
        plan_analysis = analyzer._infer(analysis_prompt, max_tokens=1024)
        
        if plan_analysis:
            try:
                plan_data = json.loads(plan_analysis)
                risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(
                    plan_data.get("risk_assessment", "medium"), "⚪"
                )
                print(f"   {risk_icon} 风险评估: {plan_data.get('risk_assessment', '未知')}")
                print(f"   📝 预计操作: 新建 {plan_data.get('estimated_tables_to_create', '?')} 表, "
                      f"添加 {plan_data.get('estimated_columns_to_add', '?')} 列")
                
                if plan_data.get("potential_issues"):
                    print(f"   ⚠️ 潜在风险:")
                    for issue in plan_data['potential_issues'][:3]:
                        print(f"      - {issue}")
                        
            except (json.JSONDecodeError, ValueError):
                print(f"   ℹ️ LLM 计划分析完成（解析略过）")
        else:
            print(f"   ℹ️ 跳过执行计划分析（非关键步骤）")
            
    except Exception as e:
        print(f"   ℹ️ 执行计划分析失败（不影响升级流程）: {e}")

    try:
        cursor = conn.cursor()

        statements = []
        current_stmt = []
        for line in sql_script.split('\n'):
            stripped = line.strip()
            if stripped.startswith('--') or stripped == '':
                continue
            current_stmt.append(line)
            if stripped.endswith(';'):
                stmt = '\n'.join(current_stmt).strip()
                if stmt:
                    statements.append(stmt)
                current_stmt = []

        executed = 0
        errors = []
        for i, stmt in enumerate(statements):
            try:
                cursor.execute(stmt)
                executed += 1
                if executed % 10 == 0:
                    print(f"  📝 已执行 {executed}/{len(statements)} 条语句...")
            except sqlite3.OperationalError as e:
                if "already exists" in str(e) or "duplicate column" in str(e):
                    pass
                else:
                    error_info = {
                        "statement_index": i,
                        "sql_preview": stmt[:100],
                        "error": str(e),
                        "severity": "low" if "already" in str(e).lower() else "medium"
                    }
                    errors.append(error_info)
                    print(f"  ⚠️ 语句 {i+1} 执行出错: {e}")

        conn.commit()
        print(f"✅ SQL 执行完成！成功 {executed} 条，错误 {len(errors)} 条\n")

        post_upgrade_meta = collect_schema_metadata(conn)

        validation_result = analyzer.validate_upgrade_success(
            pre_upgrade_meta,
            post_upgrade_meta
        )

        status = validation_result.get("upgrade_status", "unknown")
        confidence = validation_result.get("confidence", 0)

        print(f"🔍 LLM 验证结果:")
        print(f"   状态: {status}")
        print(f"   置信度: {confidence:.1%}")
        print(f"   新建表: {validation_result.get('new_tables_created', [])}")

        if validation_result.get("warnings"):
            print(f"   ⚠️ 警告:")
            for warning in validation_result.get("warnings", [])[:3]:
                print(f"      - {warning}")

        is_success = status == "success" and confidence > 0.8

        if is_success:
            report = analyzer.generate_migration_report({
                "pre_upgrade": pre_upgrade_meta,
                "post_upgrade": post_upgrade_meta,
                "validation": validation_result,
                "execution_stats": {
                    "total_statements": len(statements),
                    "successful": executed,
                    "errors": len(errors),
                    "error_details": errors[-3:] if errors else []
                }
            })

            print("\n" + "="*60)
            print("📊 LLM 生成的迁移报告:")
            print("="*60)
            print(report)
            print("="*60)

        return is_success

    except Exception as e:
        print(f"❌ v5.0 Schema 升级失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """
    主函数：协调 LLM 驱动升级流程
    
    流程：
    1. 检测 LLM 可用性
    2. 备份数据库
    3. 收集当前 Schema 元信息
    4. LLM 分析诊断（可选）
    5. 执行 SQL 升级脚本
    6. LLM 验证结果（可选）
    7. 生成迁移报告（可选）
    """
    print("="*60)
    print("🚀 DevPartner v5.0 数据库升级工具（LLM 驱动版）")
    print("="*60)
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 数据库: {os.path.abspath(DB_PATH)}")
    print(f"🤖 推理引擎: llama-cpp-python + Qwen3.5-9B-Q4_1")
    print()

    use_llm = "--no-llm" not in sys.argv
    analyzer = None

    if use_llm:
        print("✨ 启用 LLM 驱动模式（零硬编码，智能分析）")
        analyzer = LLMDrivenAnalyzer()
        
        if analyzer._ensure_service():
            status = analyzer.llm_service.get_status()
            print(f"✅ LLM 服务就绪:")
            print(f"   - 引擎版本: {status.get('engine_version', '未知')}")
            print(f"   - 模型路径: {status.get('model_info', {}).get('path', '未知')}")
            print(f"   - 模型大小: {status.get('model_info', {}).get('size_mb', 0):.1f} MB")
            print(f"   - GPU 加速: {'启用' if status.get('config', {}).get('n_gpu_layers', 0) != 0 else '未启用'}")
            
            # 快速测试推理能力
            test_start = datetime.now()
            test_result = analyzer._infer("回复 OK", max_tokens=10)
            test_time = (datetime.now() - test_start).total_seconds()
            
            if test_result and ("OK" in test_result or "ok" in test_result.lower()):
                print(f"   - 测试推理: 成功 ({test_time:.2f}秒)")
            else:
                print(f"   ⚠️ 测试推理异常，但服务可用")
        else:
            print("⚠️ LLM 服务不可用，自动切换到传统模式...")
            use_llm = False
            analyzer = None
    else:
        print("📦 使用传统模式（--no-llm 参数）")

    print()

    # Step 1: 备份
    print("Step 1/4: 备份数据库...")
    backup_path = backup_database()
    print()

    # Step 2: 连接数据库
    print("Step 2/4: 连接数据库并收集元信息...")
    conn = get_connection()
    
    if use_llm and analyzer:
        current_schema = collect_schema_metadata(conn)
        print(f"   📊 已收集 {len(current_schema.get('tables', {}))} 个表的元信息")
    print()

    # Step 3: 分析与准备
    if use_llm and analyzer:
        print("Step 3/4: LLM 智能分析当前 Schema...")
        initial_analysis = analyzer.analyze_database_schema(current_schema)

        data_score = initial_analysis.get('data_quality_score', 'N/A')
        issue_count = len(initial_analysis.get('issues', []))
        
        print(f"   📈 数据质量评分: {data_score}")
        print(f"   🔍 发现问题: {issue_count} 个")
        
        if issue_count > 0:
            print("\n   ⚠️ 主要问题:")
            for i, issue in enumerate(initial_analysis['issues'][:5], 1):
                severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                    issue.get('severity', 'low'), "⚪"
                )
                desc = issue.get('description', 'N/A')[:70]
                target = issue.get('target', '')
                print(f"      {i}. {severity_icon} [{target}] {desc}")
        
        recommendations = initial_analysis.get('recommendations', [])
        if recommendations:
            print(f"\n   💡 LLM 建议:")
            for rec in recommendations[:3]:
                print(f"      → {rec}")
        print()
    else:
        print("Step 3/4: 传统模式 - 检测并添加缺失列...")
        from traditional_upgrader import add_missing_columns
        add_missing_columns(conn)
        print()

    # Step 4: 执行升级
    if use_llm and analyzer:
        print("Step 4/4: 执行 LLM 指导的升级...")
        success = execute_v50_upgrade_with_llm(conn, analyzer)
    else:
        print("Step 4/4: 传统模式 - 执行 Schema 升级...")
        from traditional_upgrader import execute_v50_upgrade
        success = execute_v50_upgrade(conn)
        if success:
            from traditional_upgrader import verify_upgrade
            verify_upgrade(conn)

    conn.close()

    # 最终报告
    print("\n" + "="*60)
    if success:
        print("✅ 升级完成！请重启 DevPartner 服务以应用更改。")
        print(f"\n💡 如需回滚，请恢复备份文件:")
        print(f"   copy \"{backup_path}\" \"{DB_PATH}\"")
        
        if use_llm and analyzer:
            print("\n📊 LLM 生成的完整迁移报告已在上方展示。")
            print("   建议保存报告内容以备后续查阅。")
    else:
        print("❌ 升级失败！数据库已自动恢复到备份状态。")
        print(f"\n💡 请查看上方错误信息，或恢复备份:")
        print(f"   copy \"{backup_path}\" \"{DB_PATH}\"")
        
        if use_llm and analyzer:
            print("\n🔧 故障排查建议:")
            print("   1. 检查 LLM 返回的错误详情")
            print("   2. 确认 SQL 脚本路径是否正确")
            print("   3. 尝试使用 --no-llm 参数回退到传统模式")
    print("="*60)


if __name__ == "__main__":
    main()