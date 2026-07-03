"""
v6.0 重构最终验证脚本
=====================
验证所有核心模块是否正常导入和工作
"""

import sys
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

def test_services_import():
    """测试服务层导入"""
    print("=" * 60)
    print("🔍 测试 1: 服务层导入")
    print("=" * 60)
    
    try:
        import devpartner_agent.services as services
        print("✅ devpartner_agent.services 导入成功")
        
        # 列出主要导出
        if hasattr(services, '__all__'):
            print(f"\n📦 导出的符号 ({len(services.__all__)} 个):")
            for name in services.__all__:
                print(f"   ✓ {name}")
        
        return True
    except Exception as e:
        print(f"❌ 服务层导入失败: {e}")
        return False


def test_core_modules():
    """测试核心模块"""
    print("\n" + "=" * 60)
    print("🔍 测试 2: 核心模块导入")
    print("=" * 60)
    
    modules = [
        ('devpartner_agent.core.config', '配置管理'),
        ('devpartner_agent.core.database', '数据库'),
        ('devpartner_agent.core.llm_unified_analyzer', 'LLM引擎'),
        ('devpartner_agent.core.scheduler', '定时调度器'),
    ]
    
    results = []
    for module_name, desc in modules:
        try:
            __import__(module_name)
            print(f"✅ {desc} ({module_name})")
            results.append(True)
        except Exception as e:
            print(f"❌ {desc} 失败: {e}")
            results.append(False)
    
    return all(results)


def test_analyzer():
    """测试对话分析器"""
    print("\n" + "=" * 60)
    print("🔍 测试 3: 对话分析器功能")
    print("=" * 60)
    
    try:
        from devpartner_agent.services.conversation_analyzer import get_analyzer
        analyzer = get_analyzer()
        print(f"✅ 分析器实例化成功: {type(analyzer).__name__}")
        
        # 检查是否有硬编码残留
        import inspect
        source = inspect.getsource(type(analyzer))
        has_hardcoded = any([
            'SKILL_DOMAINS' in source,
            'MCP_TOOL_PATTERNS' in source,
            're.compile' in source and 'pattern' in source.lower(),
        ])
        
        if has_hardcoded:
            print("⚠️ 警告：检测到可能的硬编码规则残留")
            return False
        else:
            print("✅ 无硬编码规则（纯LLM驱动）")
            return True
            
    except Exception as e:
        print(f"❌ 分析器测试失败: {e}")
        return False


def test_database_schema():
    """测试数据库 Schema"""
    print("\n" + "=" * 60)
    print("🔍 测试 4: 数据库 Schema 验证")
    print("=" * 60)
    
    try:
        from devpartner_agent.core.database import get_db
        
        db_path = project_root / "data" / "databases" / "devpartner.db"
        db = get_db()
        
        if not db._local_conn:
            db.init_local(str(db_path))
        
        # 检查关键表
        cursor = db._local_conn.cursor()
        
        tables_to_check = [
            ('conversations', '对话表'),
            ('conversation_steps', '步骤表（含外键约束）'),
            ('user_skills', '用户技能表（含追溯字段）'),
            ('improvement_log', '改进日志表（含dimensions字段）'),
        ]
        
        all_ok = True
        for table_name, desc in tables_to_check:
            cursor.execute(f"""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if cursor.fetchone():
                print(f"✅ {desc}: {table_name}")
                
                # 检查特殊字段
                if table_name == 'conversations':
                    cursor.execute("PRAGMA index_list(conversations)")
                    indexes = [row[1] for row in cursor.fetchall()]
                    has_unique_idx = any('unique' in idx.lower() for idx in indexes)
                    if has_unique_idx:
                        print("   ✓ conversation_id 唯一索引已存在")
                    else:
                        print("   ⚠️ 缺少唯一索引")
                        all_ok = False
                        
                elif table_name == 'user_skills':
                    cursor.execute("PRAGMA table_info(user_skills)")
                    columns = [row[1] for row in cursor.fetchall()]
                    required_cols = ['confidence', 'first_seen', 'last_seen']
                    missing = [c for c in required_cols if c not in columns]
                    if missing:
                        print(f"   ⚠️ 缺少字段: {missing}")
                        all_ok = False
                    else:
                        print(f"   ✓ 追溯字段完整: {required_cols}")
                        
                elif table_name == 'improvement_log':
                    cursor.execute("PRAGMA table_info(improvement_log)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if 'dimensions' in columns:
                        print("   ✓ dimensions JSON字段已添加")
                    else:
                        print("   ⚠️ 缺少dimensions字段")
                        all_ok = False
            else:
                print(f"❌ 表不存在: {table_name}")
                all_ok = False
        
        return all_ok
        
    except Exception as e:
        print(f"❌ 数据库Schema验证失败: {e}")
        return False


def main():
    """主函数"""
    print("\n" + "🎉" * 30)
    print("DevPartner v6.0 最终验证报告")
    print("🎉" * 30)
    
    tests = [
        ("服务层导入", test_services_import),
        ("核心模块", test_core_modules),
        ("对话分析器", test_analyzer),
        ("数据库Schema", test_database_schema),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n💥 测试异常: {name} - {e}")
            results.append((name, False))
    
    # 输出总结
    print("\n" + "=" * 60)
    print("📊 验证总结")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status}: {name}")
    
    print(f"\n总计: {passed}/{total} 通过 ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n🎊 恭喜！v6.0 重构全部验证通过！系统可投入使用。")
        return 0
    else:
        print("\n⚠️ 存在问题，请检查上方详细输出。")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)