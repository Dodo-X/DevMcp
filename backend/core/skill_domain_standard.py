"""
技能领域标准化模块 v9.5.1
========================

统一维护技能名→标准领域的映射关系，作为全项目的单一数据源。

所有需要将细粒度技能名归类到标准领域的代码，都应该通过本模块的
normalize_domain() 函数，而不是各自维护一套映射表。

标准领域列表（7个）：
- Python、前端、AI/LLM、DevOps、数据库、架构设计、通用工程
"""

# ── 标准领域列表 ──
STANDARD_DOMAINS = [
    "Python",
    "前端",
    "AI/LLM",
    "DevOps",
    "数据库",
    "架构设计",
    "通用工程",
]

STANDARD_DOMAINS_SET = set(STANDARD_DOMAINS)

# ── 关键词 → 标准领域 映射表（唯一数据源）──
# 规则：子串匹配（keyword.lower() in skill_str.lower()），命中第一个即返回
DOMAIN_KEYWORD_MAP = {
    # AI/LLM 大类 — 所有 AI/LLM/Agent/Prompt/模型相关
    "AI/LLM": [
        "Ponytail",
        "MCP",
        "LLM",
        "RAG",
        "Agent",
        "Prompt",
        "大模型",
        "机器学习",
        "深度学习",
        "NLP",
        "Ollama",
        "OpenAI",
        "AI",
        "ML",
        "GPT",
        "Claude",
        "FastMCP",
        "模型",
        "推理",
        "向量",
        "Embedding",
        "对话分析",
        "知识图谱",
    ],
    # 前端
    "前端": [
        "前端",
        "Frontend",
        "React",
        "Vue",
        "JavaScript",
        "TypeScript",
        "HTML",
        "CSS",
        "Webpack",
        "Vite",
        "Node",
        "UI",
        "组件",
        "浏览器",
        "DOM",
        "dom",
        "前后端联调",
    ],
    # Python
    "Python": [
        "Python",
        "Django",
        "FastAPI",
        "Flask",
        "pip",
        "conda",
        "pytest",
        "py",
        "后端开发",
        "后端",
        "Pythonic",
        "环境管理",
        "多线程编程",
    ],
    # DevOps
    "DevOps": [
        "DevOps",
        "Docker",
        "Kubernetes",
        "CI/CD",
        "Linux",
        "Nginx",
        "Git",
        "部署",
        "运维",
        "容器",
        "Shell",
        "cron",
        "GitHub",
    ],
    # 数据库
    "数据库": [
        "SQL",
        "MySQL",
        "PostgreSQL",
        "SQLite",
        "Redis",
        "MongoDB",
        "数据库",
        "ORM",
        "SQLAlchemy",
        "索引",
        "查询优化",
        "WAL",
    ],
    # 架构设计
    "架构设计": [
        "架构",
        "设计模式",
        "系统设计",
        "微服务",
        "异步",
        "并发",
        "管道",
        "队列",
        "设计",
        "SOLID",
        "系统架构",
        "指数退避",
        "API设计",
        "重构",
    ],
    # 通用工程
    "通用工程": [
        "代码质量",
        "安全",
        "调试",
        "测试",
        "文档",
        "问题定位",
        "工程",
        "最佳实践",
        "编码规范",
        "YAGNI",
        "DRY",
        "清理",
        "新技术",
        "数据生命周期",
        "devpartner",
    ],
}


def normalize_domain(skill_or_domain: str) -> str:
    """
    将任意技能名/领域名标准化为 7 个标准领域之一。

    如果输入已经是标准领域名，直接返回。
    否则通过关键词子串匹配归类，无法匹配的返回 "通用工程"。

    Args:
        skill_or_domain: 技能名或领域名（如 "Ponytail原则", "Python后端开发", "前端调试"）

    Returns:
        标准领域名（如 "AI/LLM", "Python", "前端"）

    Examples:
        >>> normalize_domain("Ponytail 原则")
        'AI/LLM'
        >>> normalize_domain("Python后端开发")
        'Python'
        >>> normalize_domain("前端调试")
        '前端'
        >>> normalize_domain("Python")  # 已经是标准领域
        'Python'
        >>> normalize_domain("某个未知技能")
        '通用工程'
    """
    if not skill_or_domain:
        return "通用工程"

    s = str(skill_or_domain).strip()

    # 如果已经是标准领域名，直接返回
    if s in STANDARD_DOMAINS_SET:
        return s

    # 关键词子串匹配
    s_lower = s.lower()
    for domain, keywords in DOMAIN_KEYWORD_MAP.items():
        for kw in keywords:
            if kw.lower() in s_lower:
                return domain

    # 无法匹配，归入通用工程
    return "通用工程"


def is_standard_domain(domain: str) -> bool:
    """检查是否为标准领域名"""
    return str(domain).strip() in STANDARD_DOMAINS_SET
