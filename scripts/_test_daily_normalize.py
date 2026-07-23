# E2E test for daily report normalization
import json, sys, tempfile, os
sys.path.insert(0, '.')

user_json = {
  'date': '2026-07-23',
  'summary': '今日完成知识库表结构优化和MD文档生成链路的修复',
  'facts': ['14次对话，debug 8次占57%', '完成3个模块代码重构', '成功审计并清理了知识库表冗余字段'],
  'experience': {
    'deep_dive': '今天最深入的技术探索...',
    'lesson': '今天学到的重要经验...',
    'skills': {'patterns': ['发现并优化数据库冗余字段']},
    'knowledge': {
      'insights': ['通过三向对比发现知识库中多个冗余字段'],
      'bugs': [
        {'category': '编码错误', 'description': 'knowledge_points 表中存在冗余字段', 'root_cause': 'DDL-INSERT-SELECT不一致', 'solution': '移除无用字段'}
      ],
      'solutions': ['修复知识库冗余字段问题'],
      'decisions': ['通过三向对比定期审计数据表'],
      'projects': [{'project_name': 'devPartner', 'work_summary': '审计和优化', 'bugs_found': [], 'bugs_fixed': [{'description': '冗余字段', 'solution': '移除无用字段'}]}]
    },
    'danger_signals': ['未及时更新任务队列handler'],
    'tech_debt': ['项目存在多处硬编码模板字符串'],
    'growth_plan': ['每次代码修改后补充单元测试']
  },
  'self_analysis': {
    'strengths': ['能够系统性定位问题'],
    'weaknesses': ['代码更新后缺少完整验证'],
    'growth_suggestions': ['每次迭代增加测试，长期关注架构解耦'],
    'metrics': {
      'productivity_score': {'score': 7, 'evidence': '完成知识库、MD链路修复工作'},
      'learning_score': {'score': 8, 'evidence': '掌握数据表三向审计'},
    },
    'psychology': {
      'frustration_level': 2,
      'flow_signals': ['重构调试连续3小时无外部干扰'],
      'decision_style': '系统性分析决策',
      'recurring_blockers': ['部分模块混入模板字符串']
    }
  }
}

# Test 1: Normalization
from backend.business.task_handlers.daily_engine import _normalize_daily_report_json
_normalize_daily_report_json(user_json)

print('After normalization, top-level keys:')
for k in sorted(user_json.keys()):
    v = user_json[k]
    if isinstance(v, dict):
        print(f'  {k}: {list(v.keys())[:5]}')
    elif isinstance(v, list):
        print(f'  {k}: [{len(v)} items]')
    else:
        print(f'  {k}: {str(v)[:60]}')

assert 'skills' in user_json, 'skills should be top-level'
assert 'knowledge' in user_json, 'knowledge should be top-level'
assert 'danger_signals' in user_json, 'danger_signals should be top-level'
assert 'growth_plan' in user_json, 'growth_plan should be top-level'
assert 'project_analysis' in user_json, 'project_analysis should be top-level'
assert 'metrics' in user_json, 'metrics should be top-level'
assert 'psychology' in user_json, 'psychology should be top-level'
print('\nNormalization: ALL CHECKS PASSED')

# Test 2: Assemble MD
from backend.business.vault_export.md_templates import register_all
from backend.business.vault_export.md_engine import get_assembler

with tempfile.TemporaryDirectory() as tmp:
    assembler = get_assembler(vault_root=tmp)
    register_all(assembler)
    
    data = {'date_str': '2026-07-23', 'report_data': user_json}
    md = assembler.assemble('daily_report', data)
    
    section_count = md.count('## ')
    print(f'\nMD sections rendered: {section_count}')
    for line in md.split('\n'):
        if line.startswith('## '):
            print(f'  {line}')
    
    print(f'\nTotal MD length: {len(md)} chars')
    
    # Verify key content present
    assert 'Bug' in md, 'Bug section should be in MD'
    assert '成长' in md, 'growth_plan section should be in MD'
    assert '自我反思' in md, 'self_analysis section should be in MD'
    assert '优势' in md, 'strengths should be in MD'
    print('Content checks: ALL PASSED')
    print('\nE2E test PASSED!')
