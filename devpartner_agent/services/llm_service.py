"""
本地 LLM 服务 (v7.3.0 — Ollama 引擎)
======================================
通过本地 Ollama 服务（http://localhost:11434）进行推理。
完全替代 llama-cpp-python，利用已安装的 Ollama 实例。

设计原则：
- 单引擎架构：仅使用 Ollama HTTP API
- 零模型文件管理：模型由 Ollama 自身管理
- 单例 + 懒加载：连接惰性建立
- 线程安全：推理过程加锁，避免并发冲突
- 智能提示工程：针对中文场景优化的 Prompt
- 性能监控：记录推理时间和资源使用情况
"""

import json
import logging
import os
import re
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

_KNOWN_DOMAINS = [
    "Python", "前端", "DevOps", "数据库", "AI/ML", "系统设计", "安全", "代码质量",
]

# ── Prompt 模板 ──

_CONVERSATION_ANALYSIS_PROMPT = """你是一个专业的开发者对话分析 AI 助手。请分析以下开发者与 AI 的对话内容，提取关键信息并输出结构化 JSON。

## 对话元信息
- 来源: {source}
- 客户端: {client}

## 对话原文
{content}

## 输出要求
请严格按照以下 JSON 格式输出（不要包含 markdown 代码块标记）:

{{
  "summary": "用一句话概括对话的核心内容（50字以内）",
  "skill_domains": [
    {{
      "domain": "技术领域名称（如：Python、前端、DevOps、数据库、AI/ML等）",
      "sub_skills": ["具体技术栈或技能点1", "技能点2"],
      "match_score": 0.95
    }}
  ],
  "complexity": "根据问题复杂度选择: simple(简单问答) / multi_step(多步骤) / complex(复杂系统级)",
  "user_feedback": {{
    "has_feedback": 是否包含用户纠正/不满/追问信号 (true/false),
    "types": ["反馈类型列表: 纠正/补充/不满/重试/追问"],
    "severity": "反馈严重程度: none/low/medium/high"
  }},
  "tool_gaps": [
    {{
      "tool": "应该调用但未调用的 MCP 工具名称",
      "reason": "为什么这个工具应该被调用"
    }}
  ],
  "optimization_suggestions": [
    {{
      "type": "优化类型: tool_description_weak/tool_logic_error/missing_optimization",
      "target_tool": "相关工具名称",
      "description": "问题描述",
      "suggestion": "具体改进建议",
      "priority": "优先级: low/medium/high"
    }}
  ],
  "user_traits": {{
    "skills_observed": ["用户展现的技术技能"],
    "behavior_notes": "用户的行为模式观察",
    "mistakes": ["用户犯过的错误或踩过的坑"],
    "strengths": ["用户的强项和优势"],
    "communication_style": "沟通风格: 直接/委婉/详细/简洁",
    "decision_pattern": "决策模式: 数据驱动/直觉/谨慎/大胆",
    "tech_interests": ["感兴趣的技术方向"],
    "areas_for_growth": ["需要提升的领域"]
  }}
}}

注意：
1. 只输出 JSON，不要添加任何解释性文字
2. skill_domains 从以下已知领域选择或合理新增: {domains}
3. match_score 范围 0.0-1.0，表示匹配置信度
4. 所有字段都必须填写，不确定的字段填默认值"""

_FILE_PARSE_PROMPT = """你是一个专业的文档解析 AI 助手。请将以下 Markdown 格式的对话记忆文件拆分为独立的对话条目。

## 文件信息
- 文件名: {filename}

## 文件内容
{content}

## 输出要求
请严格按照以下 JSON 格式输出:

{{
  "conversations": [
    {{
      "time": "对话时间 (格式: HH:MM 或 00:00)",
      "topic": "对话主题概括（100字以内）",
      "content": "该条对话的完整原文内容",
      "source": "对话来源: codebuddy/cursor/windsurf/trae/unknown"
    }}
  ]
}}

解析规则：
1. 每个对话条目应该是完整的语义单元
2. 如果文件中包含 source 或 client 标记，提取到 source 字段
3. 如果无法明确拆分，将整个文件作为一条对话
4. 保留原文的完整性，不要省略关键信息
5. 只输出 JSON，不要其他文字"""

_DAILY_SUMMARY_PROMPT = """你是一个专业的开发者工作总结 AI 助手。基于以下今日工作数据，生成结构化的日报分析。

## 今日日期
{date}

## 工作数据概览
- 对话总数: {total_conversations}
- 涉及文件数: {files_count}
- 主要任务类型: {task_types}

## 详细对话记录
{conversations}

## 输出要求
请生成完整的 JSON 格式日报:

{{
  "date": "{date}",
  "summary": "一句话总结今天的主要工作成果（100字以内）",
  "experience": {{
    "deep_dive": "今天最深入的技术探索或解决的问题（200字以内）",
    "lesson": "今天学到的重要经验或教训（150字以内）"
  }},
  "skills": {{
    "new_skills": ["今天新接触或使用的技能"],
    "patterns": ["发现的模式或规律"],
    "tools": ["使用过的工具清单"]
  }},
  "knowledge": {{
    "must_remember": ["必须记住的关键知识点"],
    "insights": ["重要洞察和发现"]
  }},
  "danger_signals": {{
    "repeated_mistakes": ["重复出现的错误"],
    "tech_debt": ["积累的技术债务"],
    "hot_files": ["频繁修改的高风险文件"]
  }},
  "tomorrow_plan": "明天最优先要完成的1-3件事",
  "self_analysis": {{
    "strengths": ["今天的优点和做得好的地方"],
    "weaknesses": ["需要改进的地方"],
    "growthSuggestions": ["具体的成长建议"]
  }},
  "metrics": {{
    "productivity_score": 工作效率自评分 (1-10),
    "learning_score": 学习成长分 (1-10),
    "collaboration_score": 协作效率分 (1-10)
  }}
}}

注意：
1. 基于实际数据进行分析，不要编造
2. 突出重点，避免流水账
3. 只输出 JSON"""

_SELF_IMPROVEMENT_PROMPT = """你是一个专业的系统自我优化 AI 助手。基于以下 DevPartner 系统运行数据，生成改进建议。

## 系统运行数据
{system_data}

## 历史优化记录
{improvement_history}

## 输出要求
请分析系统状态并输出改进建议 JSON:

{{
  "analysis": {{
    "system_health": "系统健康度评估: excellent/good/fair/poor",
    "key_findings": ["关键发现1", "发现2"],
    "pain_points": ["痛点问题1", "问题2"]
  }},
  "suggestions": [
    {{
      "category": "建议类别: performance/usability/reliability/feature/mcp_tool_cleanup/mcp_tool_hotspot",
      "priority": "优先级: high/medium/low",
      "suggestion": "具体建议描述",
      "expected_impact": "预期影响",
      "effort": "实现难度: easy/medium/hard",
      "detail": {{
        "action": "建议操作: review/enhance/disable/deprecate/add",
        "target_files": ["相关文件路径"],
        "current_issue": "当前问题描述",
        "proposed_solution": "解决方案概述"
      }}
    }}
  ],
  "quick_wins": [
    "可以快速实施的改进项1",
    "快速改进项2"
  ],
  "long_term_goals": [
    "长期目标1",
    "目标2"
  ]
}}

分析维度：
1. 性能瓶颈：是否有明显的性能问题
2. 用户体验：工具使用是否流畅
3. 功能覆盖：是否有缺失的重要功能
4. MCP 工具：工具集是否需要清理或增强
5. 代码质量：是否需要重构或优化
6. 用户反馈：历史反馈问题的解决情况"""

_STEP_ANALYSIS_PROMPT = """你是一个专业的开发者技能分析 AI。请分析以下子任务步骤的详细内容，提取开发者的思考模式、使用的命令、涉及的语法知识点。

## 步骤信息
- 步骤名称: {step_name}
- 步骤类型: {step_type}
- 问题现象: {symptom}
- 根因分析: {root_cause}
- 解决方案: {solution}

## 步骤详细内容
{content}

## 输出要求
请严格按照以下 JSON 格式输出（不要包含 markdown 代码块标记）:

{{
  "thinking_patterns": [
    {{
      "pattern": "思考模式描述（如：自顶向下分析、逐层排查、并行搜索、假设验证等）",
      "context": "在什么场景下运用了这种思考模式",
      "effectiveness": "效果评价: high/medium/low"
    }}
  ],
  "commands_used": [
    {{
      "command": "具体的命令或操作（如：pip install, git diff, grep 等）",
      "purpose": "该命令的目的",
      "context": "在什么场景下使用的"
    }}
  ],
  "syntax_points": [
    {{
      "language": "编程语言（如：Python, JavaScript, SQL, YAML 等）",
      "pattern": "语法模式或代码片段（如：装饰器模式、async/await、列表推导式等）",
      "description": "该语法的用途说明",
      "difficulty": "难度: beginner/intermediate/advanced"
    }}
  ],
  "extracted_knowledge": [
    {{
      "title": "知识点标题",
      "desc": "知识点详细描述（便于未来按图索骥）",
      "domain": "所属技术领域",
      "tags": ["标签1", "标签2"]
    }}
  ],
  "complexity_level": "步骤复杂度: simple/medium/complex",
  "key_decision": "本步骤中最重要的技术决策（一句话）"
}}

注意：
1. 如果某字段没有数据，返回空数组 [] 或空字符串 ""
2. thinking_patterns 必须至少有 1 条（描述 AI/开发者如何思考的）
3. 只输出 JSON，不要添加任何解释性文字"""

_CONVERSATION_DEEP_ANALYSIS_PROMPT = """你是一个专业的系统架构分析师 AI。请分析以下对话的全局总结和所有步骤，聚焦于系统层面的问题和用户层面的洞察。

## 对话全局总结
{summary}

## AI 自我复盘
{self_reflection}

## 用户画像特征
{user_traits}

## 关键决策记录
{key_decisions}

## 所有步骤汇总
{steps_summary}

## 输出要求
请严格按照以下 JSON 格式输出（不要包含 markdown 代码块标记）:

{{
  "system_issues": [
    {{
      "issue": "系统层面的问题描述",
      "root_cause": "深入分析根本原因",
      "is_recurring": true,
      "recurrence_detail": "如果反复出现，描述重复模式和次数",
      "severity": "严重程度: high/medium/low",
      "affected_area": "受影响的系统模块或功能"
    }}
  ],
  "system_deficiencies": [
    {{
      "area": "存在不足的系统领域（如：错误处理、配置管理、前端展示、测试覆盖等）",
      "description": "具体不足是什么",
      "impact": "这个不足造成的影响",
      "improvement_direction": "改进方向建议"
    }}
  ],
  "user_insights": [
    {{
      "observation": "从对话中观察到的用户特征或问题",
      "pattern": "是否有某种行为模式（如：重复某个错误、倾向于某种解决方案）",
      "suggestion": "针对用户的建议"
    }}
  ],
  "recurring_patterns": [
    {{
      "pattern": "反复出现的问题或行为模式",
      "observed_count": 因无法精确已知，填 1,
      "trend": "趋势: increasing/decreasing/stable",
      "first_observed": "本次对话中首次出现的步骤"
    }}
  ],
  "overall_assessment": "对整个对话的综合评价（200字以内，聚焦大方向）",
  "risk_areas": ["需要关注的风险领域"],
  "positive_patterns": ["值得保留的好做法或好模式"]
}}

注意：
1. system_issues 聚焦于架构/设计/代码层面的系统问题，不是用户操作失误
2. system_deficiencies 聚焦于当前系统缺少的能力或做得不好的地方
3. user_insights 是反向分析用户（开发者）存在的问题或行为模式
4. 只输出 JSON，不要添加任何解释性文字"""


class LLMService:
    """
    Ollama 本地推理服务（v7.3.0）
    
    通过 Ollama HTTP API 调用本地模型进行推理。
    前提：用户已安装并运行 Ollama（ollama serve）。
    
    特性：
    - 零模型文件管理，模型由 Ollama 管理
    - OpenAI 兼容的 /api/chat 端点
    - 单例 + 线程安全
    - 性能监控
    """

    _instance: Optional["LLMService"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._lock = threading.Lock()
        self._load_error: Optional[str] = None
        self._inference_count = 0

        # 性能统计
        self._total_inference_time = 0.0
        self._last_inference_time = 0.0
        self._avg_tokens_per_second = 0.0

    def _get_config(self):
        from devpartner_agent.core.config import get_config
        return get_config().llm

    def is_enabled(self) -> bool:
        """检查 LLM 功能是否启用"""
        return getattr(self._get_config(), 'enabled', True)

    def is_available(self) -> bool:
        """
        检查 Ollama 服务是否可用。
        
        通过 GET /api/tags 检查 Ollama 是否在线。
        """
        if not self.is_enabled():
            return False

        try:
            req = urllib.request.Request(f"{_OLLAMA_BASE_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            logger.warning("Ollama 服务 (%s) 不可达", _OLLAMA_BASE_URL)
            return False

    def get_status(self) -> dict:
        """
        获取 LLM 服务详细状态信息
        """
        cfg = self._get_config()

        # 获取 Ollama 模型列表
        models = []
        try:
            req = urllib.request.Request(f"{_OLLAMA_BASE_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            pass

        status = {
            "enabled": cfg.enabled,
            "engine": "ollama",
            "engine_version": "Ollama HTTP API",
            "ollama_url": _OLLAMA_BASE_URL,
            "model_info": {
                "configured_model": getattr(cfg, 'ollama_model', 'qwen3'),
                "available_models": models,
            },
            "model_loaded": self.is_available(),
            "load_error": self._load_error,
            "inference_count": self._inference_count,
            "performance_stats": {
                "total_inference_time_sec": round(self._total_inference_time, 3),
                "last_inference_time_sec": round(self._last_inference_time, 3),
                "avg_tokens_per_second": round(self._avg_tokens_per_second, 2),
            },
            "config": {
                "model": getattr(cfg, 'ollama_model', 'qwen3'),
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "timeout_sec": getattr(cfg, 'ollama_timeout', 120),
            },
            "features": {
                "enhance_analysis": cfg.enhance_analysis,
                "enhance_file_parsing": cfg.enhance_file_parsing,
                "enhance_daily_summary": getattr(cfg, 'enhance_daily_summary', False),
                "enhance_self_improvement": getattr(cfg, 'enhance_self_improvement', False),
                "fallback_to_rules": cfg.fallback_to_rules,
            }
        }

        return status

    def preload(self) -> bool:
        """
        验证 Ollama 连接并测试推理。
        
        Ollama 模式下不加载模型文件，只需验证连接并做一次快速推理测试。
        """
        if not self.is_available():
            self._load_error = f"Ollama 服务不可达: {_OLLAMA_BASE_URL}"
            return False

        start_time = time.time()

        try:
            # 简单测试推理
            test_start = time.time()
            result = self._infer("Hello", max_tokens=10)
            test_time = time.time() - test_start

            if result is not None:
                total_time = time.time() - start_time
                logger.info(f"✅ Ollama LLM 连接成功 ({total_time:.2f}秒)")
                logger.info(f"🧪 测试推理完成 ({test_time:.2f}秒)")
                self._load_error = None
                return True
            else:
                self._load_error = "Ollama 测试推理返回空结果"
                logger.error(f"❌ Ollama LLM 连接验证失败: {self._load_error}")
                return False

        except Exception as e:
            self._load_error = f"Ollama 连接验证异常: {e}"
            logger.error(f"❌ Ollama LLM 预加载异常: {e}")
            return False

    def analyze_conversation(self, content: str, source: str = "unknown",
                             client: str = "unknown") -> Optional[dict]:
        if not self.is_available() or not self._get_config().enhance_analysis:
            return None

        cfg = self._get_config()
        truncated = self._truncate_content(content, cfg.max_input_chars)
        prompt = _CONVERSATION_ANALYSIS_PROMPT.format(
            source=source,
            client=client,
            content=truncated,
            domains="、".join(_KNOWN_DOMAINS),
        )

        raw = self._infer(prompt, cfg.max_tokens)
        if not raw:
            return None

        parsed = self._parse_json(raw)
        if not parsed:
            return None

        return self._normalize_analysis(parsed)

    def parse_file_conversations(self, content: str, filename: str) -> Optional[list[dict]]:
        if not self.is_available() or not self._get_config().enhance_file_parsing:
            return None

        cfg = self._get_config()
        truncated = self._truncate_content(content, cfg.max_input_chars)
        prompt = _FILE_PARSE_PROMPT.format(filename=filename, content=truncated)

        raw = self._infer(prompt, cfg.max_tokens)
        if not raw:
            return None

        parsed = self._parse_json(raw)
        if not parsed or "conversations" not in parsed:
            return None

        conversations = []
        for item in parsed.get("conversations", []):
            if not isinstance(item, dict):
                continue
            conv_content = item.get("content", "").strip()
            if not conv_content:
                continue
            conversations.append({
                "time": item.get("time", "00:00"),
                "topic": str(item.get("topic", "未分类"))[:100],
                "topic_hash": str(hash(conv_content[:200]))[-8:],
                "content": conv_content,
                "source": item.get("source", "unknown"),
            })
        return conversations if conversations else None

    def generate_daily_summary(self, date_str: str, work_data: dict) -> Optional[dict]:
        if not self.is_available():
            return None

        cfg = self._get_config()
        if not getattr(cfg, 'enhance_daily_summary', False):
            return None

        try:
            conversations_json = json.dumps(work_data.get("conversations", [])[:20],
                                           ensure_ascii=False, indent=2)

            prompt = _DAILY_SUMMARY_PROMPT.format(
                date=date_str,
                total_conversations=len(work_data.get("conversations", [])),
                files_count=len(work_data.get("files_touched", [])),
                task_types=", ".join(list(set(c.get("task_type", "")
                                            for c in work_data.get("conversations", [])))[:5]),
                conversations=conversations_json[:8000],
            )

            raw = self._infer(prompt, min(cfg.max_tokens * 2, 2048))
            if not raw:
                return None

            result = self._parse_json(raw)
            if result:
                result["generated_by"] = "llm"
                result["analysis_method"] = "ollama"
                result["model_info"] = {
                    "type": "ollama",
                    "inference_engine": "ollama",
                    "model": getattr(cfg, 'ollama_model', 'qwen3'),
                }
            return result

        except Exception as e:
            logger.error(f"每日总结生成失败: {e}", exc_info=True)
            return None

    def generate_self_improvement_suggestions(self, system_data: dict,
                                              improvement_history: list = None) -> Optional[list]:
        if not self.is_available():
            return None

        cfg = self._get_config()
        if not getattr(cfg, 'enhance_self_improvement', False):
            return None

        try:
            history_json = json.dumps(improvement_history or [], ensure_ascii=False, indent=2)[:3000]
            system_data_json = json.dumps(system_data, ensure_ascii=False, indent=2)[:5000]

            prompt = _SELF_IMPROVEMENT_PROMPT.format(
                system_data=system_data_json,
                improvement_history=history_json,
            )

            raw = self._infer(prompt, min(cfg.max_tokens * 2, 2048))
            if not raw:
                return None

            result = self._parse_json(raw)
            if result and isinstance(result.get("suggestions"), list):
                for s in result["suggestions"]:
                    s["source"] = "llm"
                    s["generated_at"] = __import__("datetime").datetime.now().isoformat()
                    s["model_type"] = getattr(self._get_config(), 'ollama_model', 'qwen3')
                return result["suggestions"]
            return None

        except Exception as e:
            logger.error(f"自我改进建议生成失败: {e}", exc_info=True)
            return None

    def analyze_step_content(self, step_name: str, step_type: str, content: str,
                              symptom: str = "", root_cause: str = "",
                              solution: str = "") -> Optional[dict]:
        if not self.is_available():
            return None

        cfg = self._get_config()
        if not getattr(cfg, 'enhance_analysis', True):
            return None

        try:
            content_truncated = self._truncate_content(content, cfg.max_input_chars)
            prompt = _STEP_ANALYSIS_PROMPT.format(
                step_name=step_name or "未知步骤",
                step_type=step_type or "general",
                symptom=symptom or "无",
                root_cause=root_cause or "无",
                solution=solution or "无",
                content=content_truncated,
            )

            raw = self._infer(prompt, min(cfg.max_tokens * 2, 2048))
            if not raw:
                return None

            result = self._parse_json(raw)
            if result:
                result["source"] = "llm_step_analysis"
                result["generated_at"] = __import__("datetime").datetime.now().isoformat()
            return result

        except Exception as e:
            logger.error(f"步骤内容分析失败: {e}", exc_info=True)
            return None

    def analyze_conversation_deep(self, summary: str, self_reflection: str,
                                   user_traits: dict, key_decisions: list,
                                   steps_summary: list) -> Optional[dict]:
        if not self.is_available():
            return None

        cfg = self._get_config()
        if not getattr(cfg, 'enhance_analysis', True):
            return None

        try:
            steps_str = json.dumps(steps_summary, ensure_ascii=False, indent=2)[:10000]
            traits_str = json.dumps(user_traits or {}, ensure_ascii=False, indent=2)
            decisions_str = json.dumps(key_decisions or [], ensure_ascii=False, indent=2)

            prompt = _CONVERSATION_DEEP_ANALYSIS_PROMPT.format(
                summary=summary or "无",
                self_reflection=self_reflection or "无",
                user_traits=traits_str,
                key_decisions=decisions_str,
                steps_summary=steps_str,
            )

            raw = self._infer(prompt, min(cfg.max_tokens * 2, 2048))
            if not raw:
                return None

            result = self._parse_json(raw)
            if result:
                result["source"] = "llm_conversation_deep_analysis"
                result["generated_at"] = __import__("datetime").datetime.now().isoformat()
            return result

        except Exception as e:
            logger.error(f"对话深层分析失败: {e}", exc_info=True)
            return None

    # ══════════════════════════════════════════════════════════
    # 内部辅助方法
    # ══════════════════════════════════════════════════════════

    def _truncate_content(self, content: str, max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        return content[:max_chars - 3] + "..."

    def _parse_json(self, raw: str) -> dict | None:
        if not raw:
            return None
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        json_str = m.group(1) if m else raw
        json_str = json_str.strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            try:
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning("无法解析 LLM JSON 输出: %s...", json_str[:200])
                return None

    def _normalize_analysis(self, parsed: dict) -> dict:
        return {
            "skill_domains": parsed.get("skill_domains", []),
            "complexity": parsed.get("complexity", "medium"),
            "feedback_type": parsed.get("feedback_type", "none"),
            "user_traits": parsed.get("user_traits", {}),
            "tool_gaps": parsed.get("tool_gaps", []),
            "summary": parsed.get("summary", ""),
        }

    def _infer(self, prompt: str, max_tokens: int) -> Optional[str]:
        """
        通过 Ollama HTTP API 执行推理。
        
        使用 OpenAI 兼容的 /api/chat 端点：
        POST http://localhost:11434/api/chat
        """
        cfg = self._get_config()
        model_name = getattr(cfg, 'ollama_model', 'qwen3')
        timeout = getattr(cfg, 'ollama_timeout', 120)

        try:
            inference_start = time.time()

            payload = json.dumps({
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "temperature": cfg.temperature,
                    "top_p": getattr(cfg, 'top_p', 0.9),
                    "top_k": getattr(cfg, 'top_k', 40),
                    "repeat_penalty": getattr(cfg, 'repeat_penalty', 1.1),
                    "num_predict": max_tokens,
                    "stop": ["```"],
                },
            }).encode("utf-8")

            with self._lock:
                self._inference_count += 1

                req = urllib.request.Request(
                    f"{_OLLAMA_BASE_URL}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))

            inference_time = time.time() - inference_start
            self._last_inference_time = inference_time
            self._total_inference_time += inference_time

            content = body.get("message", {}).get("content", "").strip()

            if content:
                estimated_tokens = len(content.split()) + len(content) // 2
                if inference_time > 0:
                    self._avg_tokens_per_second = (
                        (self._avg_tokens_per_second * (self._inference_count - 1) +
                         estimated_tokens / inference_time) / self._inference_count
                    )

                logger.debug(f"🤖 Ollama 推理成功 | "
                           f"模型: {model_name} | "
                           f"耗时: {inference_time:.2f}s | "
                           f"输出长度: {len(content)} 字符 | "
                           f"累计调用: {self._inference_count} 次")

                return content
            else:
                logger.warning("⚠️ Ollama 返回空内容")
                return None

        except urllib.error.URLError as e:
            logger.error(f"❌ Ollama 连接失败: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Ollama 推理失败: {e}", exc_info=True)
            return None


# ══════════════════════════════════════════════════════════════
# 全局单例工厂函数
# ══════════════════════════════════════════════════════════════

_llm_service_instance = None


def get_llm_service():
    """获取全局 LLM 服务单例"""
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = LLMService()
    return _llm_service_instance
