"""直接通过 MCP HTTP API 调用 record_step 和 finalize_conversation"""
import json, httpx, sys

MCP_URL = "http://127.0.0.1:7860/mcp"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

def mcp_call(client, method, params=None):
    """发送 MCP JSON-RPC 请求"""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    resp = client.post(MCP_URL, json=req, headers=HEADERS)
    return resp.json()

def main():
    with httpx.Client(timeout=30) as client:
        # 1. Initialize
        print("=== Initialize ===")
        result = mcp_call(client, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "codebuddy", "version": "1.0"}
        })
        if "error" in result:
            print(f"ERROR: {result['error']}")
            return
        
        # 2. 获取已创建的 conversation_id
        conversation_id = "conv_b6fb11911a8b4590"
        print(f"Conversation ID: {conversation_id}")
        
        # 3. 定义所有 steps
        steps = [
            {
                "name": "需求分析：是否需要PostgreSQL",
                "type": "design",
                "content": """用户询问当前devPartner系统是否需要对接PostgreSQL来提升数据库并发读写性能。

AI分析了当前架构：
- SQLite在WAL模式下已支持多读并发
- 真正的瓶颈在于全局threading.Lock将所有操作（包括读操作）串行化
- 当前规模（单机、读多写少）不需要PostgreSQL

关键决策：暂不迁移PostgreSQL，优先优化现有SQLite锁策略。""",
                "knowledge_points": json.dumps([
                    {"title": "SQLite WAL模式并发特性", "desc": "WAL模式下支持多读并发，写操作仍需串行化。对于读多写少的场景，SQLite+WAL已足够，瓶颈通常在应用层锁而非数据库引擎。"},
                    {"title": "全局锁vs细粒度锁设计", "desc": "全局threading.Lock导致所有DB操作串行化，即使是纯SELECT也需要获取锁。优化策略：读操作不加锁（利用WAL），写操作使用专用_write_lock。"},
                    {"title": "何时需要PostgreSQL", "desc": "需要以下特性时才考虑迁移：高并发写入(>100写/s)、分布式部署、复杂查询、地理复制、多实例共享数据。"}
                ], ensure_ascii=False),
                "user_question": "当前codebuddy已经正常对接该mcp系统 当前系统 有没有对接postgresql 这样是不是对数据的并发读写更加有利？",
                "files_changed": json.dumps([])
            },
            {
                "name": "v5.3：全局锁优化为读写分离锁",
                "type": "code_change",
                "content": """将database.py中的全局_threading.Lock拆分为：
- _local_lock：仅保护init_local初始化
- _write_lock：保护所有写操作（INSERT/UPDATE/DELETE）

query_local/query_shared中的SELECT路径移除所有锁，利用SQLite WAL多读并发。
写操作使用_write_lock串行化，避免写写冲突。

这是核心优化点，也是v5.3版本的主要变更。""",
                "knowledge_points": json.dumps([
                    {"title": "SQLite线程安全策略", "desc": "SQLite在多线程环境下的最佳实践：WAL模式+读无锁+写串行。check_same_thread=False允许跨线程使用同一连接。"},
                    {"title": "Python threading.Lock粒度设计", "desc": "锁粒度越细并发越高。全局锁→读写分离锁→行级锁是递进的优化路径。当前场景读写分离已足够。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps(["devpartner_agent/core/database.py"]),
                "user_question": "需要 优化掉吧 那就先不使用postgresql"
            },
            {
                "name": "并发测试验证锁优化",
                "type": "debug",
                "content": """验证v5.3锁优化的正确性：
1. 10线程并发读 - 全部通过，验证WAL多读正常
2. 4读+2写混合 - 通过，读写不互相阻塞
3. 4线程并发写 - 通过，_write_lock正确串行化

所有测试通过，确认锁优化不影响数据正确性。""",
                "knowledge_points": json.dumps([
                    {"title": "并发测试策略", "desc": "并发优化后必须验证：纯读并发、混合读写、纯写并发三个维度。使用threading.Thread模拟并发，assert验证结果正确性。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps([]),
                "user_question": ""
            },
            {
                "name": "需求分析：总分总对话分析架构设计",
                "type": "design",
                "content": """用户指出CodeBuddy没有利用系统已有的step机制，每次只在对话结束时一次性调用record_dialogue。

用户期望的流程：
1. 每个子任务完成后异步发送数据给MCP，不阻塞后续任务
2. 所有任务结束后再做全局多维度分析

AI设计的"总分总"架构：
- 【总·开】create_conversation + get_user_profile
- 【分·中】每个子任务→record_step（异步分析）
- 【总·尾】finalize_conversation（5维全局分析）""",
                "knowledge_points": json.dumps([
                    {"title": "总分总架构模式", "desc": "适用于长对话分析：开场建会话+画像，中间每步异步沉淀数据，结尾全局分析。关键设计原则是异步不阻塞。"},
                    {"title": "对话分析维度设计", "desc": "5个分析维度：技术决策链（做了什么决策及原因）、用户画像（技能/风格/成长）、知识图谱（概念关联）、优化建议（系统改进方向）、质量评估（对话效率）。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps([]),
                "user_question": "我们这几次对话 codebuddy 都没有将一次对话拆解成step传给mcp 作数据分析沉淀..."
            },
            {
                "name": "新增record_step MCP工具",
                "type": "code_change",
                "content": """在server.py中新增record_step MCP工具（约+130行）。

核心逻辑：
1. 接收conversation_id、step_name、step_type、content等参数
2. 写入conversation_steps表（INSERT）
3. 更新conversations表的total_steps
4. 提交step_analysis异步任务到TaskQueue
5. 立即返回，不阻塞

step_type取值：code_change/debug/config/design/learn/deploy/general""",
                "knowledge_points": json.dumps([
                    {"title": "FastMCP工具开发", "desc": "使用@mcp.tool()装饰器注册工具。工具函数返回JSON字符串。参数使用类型注解自动生成schema。"},
                    {"title": "异步任务队列设计", "desc": "TaskQueue使用优先级队列，step_analysis优先级8（中等偏高）。任务提交后立即返回task_id，后台异步执行。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps(["server.py"]),
                "user_question": ""
            },
            {
                "name": "新增finalize_conversation MCP工具",
                "type": "code_change",
                "content": """在server.py中新增finalize_conversation MCP工具（约+100行）。

核心逻辑：
1. 接收conversation_id、summary、user_traits、key_decisions、knowledge_graph、self_reflection
2. 更新conversations表（self_reflection、decisions字段）
3. 提交conversation_finalize异步任务（优先级10，最高）
4. 调用mgr.complete_conversation()标记完成
5. 返回5个分析维度列表""",
                "knowledge_points": json.dumps([
                    {"title": "对话终结分析流程", "desc": "finalize时触发：用户画像更新→关键决策记录→知识图谱构建→优化建议生成→质量评估。全部异步执行。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps(["server.py"]),
                "user_question": ""
            },
            {
                "name": "后端异步分析逻辑：task_queue.py",
                "type": "code_change",
                "content": """在task_queue.py中新增两个异步执行方法（约+150行）：

_execute_step_analysis：
- 从payload提取知识点，写入knowledge_points表
- 更新conversation_steps表状态为completed
- 递增conversations的completed_steps计数

_execute_conversation_finalize：
- 调用_apply_user_traits更新用户画像（技能、行为、偏好等）
- 记录关键决策到decisions字段
- 构建知识图谱关联
- 生成系统优化建议
- 标记conversations.analyzed=1""",
                "knowledge_points": json.dumps([
                    {"title": "用户画像模型设计", "desc": "user_traits包含：skills_observed（观察到的技能）、behavior_notes（行为模式）、mistakes（错误教训）、strengths（优势）、communication_style（沟通风格）、decision_pattern（决策模式）、tech_interests（技术兴趣）、areas_for_growth（成长方向）、emotional_state（情绪状态）。"},
                    {"title": "知识图谱构建", "desc": "从对话步骤中提取概念节点和关联边，构建知识关联网络。用于后续检索和推荐。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps(["devpartner_agent/services/task_queue.py"]),
                "user_question": ""
            },
            {
                "name": "数据库迁移：_migrate_v53",
                "type": "config",
                "content": """在database.py中新增_migrate_v53方法：

ALTER TABLE conversation_steps ADD COLUMN timeout_seconds INTEGER DEFAULT 300

原因：record_step写入conversation_steps表时需要timeout_seconds字段，但旧表没有此列。

这是v5.3版本引入的schema变更。""",
                "knowledge_points": json.dumps([
                    {"title": "SQLite ALTER TABLE限制", "desc": "SQLite仅支持有限的ALTER TABLE操作：ADD COLUMN、RENAME TABLE、RENAME COLUMN。不支持DROP COLUMN或MODIFY COLUMN。迁移策略：新增列用ADD COLUMN+默认值。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps(["devpartner_agent/core/database.py"]),
                "user_question": ""
            },
            {
                "name": "修复三个错误",
                "type": "debug",
                "content": """在总分总架构开发过程中修复了三个错误：

1. server.py中logger.error未定义（无logging import）→ 改用print
2. conversation_steps表缺少timeout_seconds列 → 添加_migrate_v53
3. conversation_manager.py中query_list/query_one方法不存在 → 改为query_local并适配返回值

这些都是v7.0开发中的常见错误：工具函数中使用未初始化的logger、schema不匹配、API调用错误。""",
                "symptom": "server.py运行时logger未定义报NameError；record_step写入数据库时报no such column: timeout_seconds；conversation_manager调用不存在的方法",
                "root_cause": "1. server.py的MCP工具函数中使用logger但未import logging\n2. 旧数据库schema缺少新增的timeout_seconds列\n3. conversation_manager使用旧API名称query_list/query_one，但database.py实际提供的是query_local",
                "solution": "1. logger.error → print\n2. 添加_migrate_v53()执行ALTER TABLE\n3. query_list/query_one → query_local，适配返回值格式",
                "knowledge_points": json.dumps([
                    {"title": "MCP工具函数中的日志策略", "desc": "MCP工具函数运行在FastMCP框架内，不一定有logging配置。安全做法：使用print输出调试信息，关键错误通过返回值传递。"},
                    {"title": "数据库迁移策略", "desc": "版本化迁移：每次schema变更添加_migrate_vXX方法，在init时按序执行。使用PRAGMA table_info检查列是否存在，避免重复添加。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps(["server.py", "devpartner_agent/core/database.py", "devpartner_agent/services/conversation_manager.py"]),
                "user_question": ""
            },
            {
                "name": "更新对话记录规则 v6.3 → v7.0",
                "type": "config",
                "content": """更新全局规则文件 auto-log-conversation.md，从v6.3升级到v7.0。

主要变更：
- 描述总分总三步流程（总·开 → 分·中 → 总·尾）
- 新增record_step调用规范（每个子任务完成后立即调用，异步不阻塞）
- 新增finalize_conversation调用规范（对话结束时5维全局分析）
- 明确CodeBuddy客户端的禁止操作（不写本地文件）
- 更新版本历史记录

规则文件位置：%USERPROFILE%/.codebuddy/rules/auto-log-conversation.md""",
                "knowledge_points": json.dumps([
                    {"title": "CodeBuddy规则系统", "desc": "规则文件存放在%USERPROFILE%/.codebuddy/rules/，所有项目自动生效。规则类型：always（每次加载）、manual（手动触发）、requested（按需加载）。"}
                ], ensure_ascii=False),
                "files_changed": json.dumps(["%USERPROFILE%/.codebuddy/rules/auto-log-conversation.md"]),
                "user_question": ""
            },
        ]
        
        # 4. 逐个提交 step
        for i, step in enumerate(steps):
            print(f"\n=== Step {i+1}/{len(steps)}: {step['name']} ===")
            
            params = {
                "conversation_id": conversation_id,
                "step_name": step["name"],
                "step_type": step["type"],
                "content": step["content"],
                "files_changed": step.get("files_changed", "[]"),
                "knowledge_points": step.get("knowledge_points", "[]"),
                "user_question": step.get("user_question", ""),
                "symptom": step.get("symptom", ""),
                "root_cause": step.get("root_cause", ""),
                "solution": step.get("solution", ""),
            }
            
            result = mcp_call(client, "tools/call", {
                "name": "record_step",
                "arguments": params
            })
            
            if "error" in result:
                print(f"  ERROR: {result['error']}")
            else:
                content = result.get("result", {}).get("content", [{}])
                text = content[0].get("text", "") if content else ""
                try:
                    data = json.loads(text)
                    print(f"  SUCCESS: step_id={data.get('step_id', 'N/A')}, total_steps={data.get('total_steps', 'N/A')}")
                except:
                    print(f"  Response: {text[:200]}")
        
        # 5. finalize_conversation
        print(f"\n=== Finalize ===")
        final_params = {
            "conversation_id": conversation_id,
            "summary": """本次对话涉及devPartner系统的两次重大升级：

## v5.3: 数据库并发锁优化
- 将全局threading.Lock拆分为_local_lock（初始化）+ _write_lock（写操作）
- SELECT操作完全移除锁，利用SQLite WAL多读并发
- 通过10线程读、4读2写混合、4线程写测试验证

## v7.0: 总分总对话分析架构
- 新增record_step工具：每个子任务完成后异步提交数据
- 新增finalize_conversation工具：对话结束5维全局分析
- 后端异步分析：知识点提取、用户画像更新、知识图谱构建
- 修复3个错误：logger未定义、表缺列、API调用错误""",
            "user_traits": json.dumps({
                "skills_observed": ["Python", "SQLite", "并发编程", "FastMCP框架", "数据库设计", "架构设计", "API设计"],
                "behavior_notes": "用户喜欢先理解全貌再动手，会主动提出架构优化建议。注重系统长期可维护性。",
                "mistakes": [],
                "strengths": ["问题定位准确（指出锁是瓶颈而非数据库）", "架构思维清晰（提出总分总设计）", "注重异步和非阻塞设计"],
                "communication_style": "直接",
                "decision_pattern": "数据驱动+架构优先",
                "tech_interests": ["AI/ML", "系统设计", "并发编程", "数据库优化", "MCP协议"],
                "areas_for_growth": ["代码审查细节"],
                "emotional_state": "专注",
                "learning_progress": "从SQLite锁优化到分布式对话分析架构，展现了从微观到宏观的技术视野"
            }, ensure_ascii=False),
            "key_decisions": json.dumps([
                {"decision": "暂不迁移PostgreSQL，优先优化SQLite锁", "reason": "当前规模不需要PostgreSQL，瓶颈在应用层锁而非数据库引擎", "tradeoff": "获得立即的性能提升，但未来高并发写入时可能需要重新评估"},
                {"decision": "采用总分总架构进行对话分析", "reason": "比一次性记录更细粒度，支持子任务级数据沉淀和对话级全局分析", "tradeoff": "增加了工具调用次数，但数据质量和分析深度大幅提升"},
                {"decision": "异步分析不阻塞客户端", "reason": "用户明确要求每个子任务完成后不等待分析结果", "tradeoff": "分析结果的即时性降低，但用户体验更好"},
                {"decision": "写操作使用_write_lock串行化", "reason": "SQLite不支持并发写，必须串行化避免database locked错误", "tradeoff": "写操作吞吐量受限，但读操作完全并发"}
            ], ensure_ascii=False),
            "self_reflection": """AI复盘：

1. **工具注册问题**：record_step/finalize_conversation在server.py中已正确使用@mcp.tool()注册，但CodeBuddy的MCP客户端因缓存旧工具列表而无法发现。这说明需要一种工具列表热更新机制，或者重启客户端连接。

2. **_collect_tool_names过期**：该函数使用mcp._tool_manager._tools（FastMCP 2.x API），在3.4.2中已改为异步list_tools()。这导致数据库工具注册表为空。需要更新此函数。

3. **MCP客户端缓存**：CodeBuddy在会话初始化时获取一次工具列表，后续不再刷新。当server重启加载新工具后，客户端不会自动感知。这是MCP协议层面的限制。

4. **测试覆盖不足**：总分总流程虽然在开发时做了端到端测试，但缺少对工具注册状态的验证，导致实际使用时才发现客户端看不到工具。"""
        }
        
        result = mcp_call(client, "tools/call", {
            "name": "finalize_conversation",
            "arguments": final_params
        })
        
        if "error" in result:
            print(f"  ERROR: {result['error']}")
        else:
            content = result.get("result", {}).get("content", [{}])
            text = content[0].get("text", "") if content else ""
            try:
                data = json.loads(text)
                print(f"  SUCCESS: conversation_id={data.get('conversation_id', 'N/A')}")
                print(f"  Analysis queued: {data.get('analysis_queued', False)}")
                print(f"  Dimensions: {data.get('analysis_dimensions', [])}")
            except:
                print(f"  Response: {text[:500]}")

if __name__ == "__main__":
    main()
