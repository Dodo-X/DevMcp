"""
MD 文档引擎 v1.0 — 模板+数据=文档 的低耦合装配架构
==================================================

设计哲学："零件化封装" — 每种 MD 文档类型注册为独立模板，
一个统一装配器负责 "模板定义 + 数据 → 完整 MD 文档"。

核心概念：
  MdSection   = 一个渲染段落（取数据的 key + 渲染函数 + 条件）
  MdTemplate  = 一份完整文档模板（标题 + 段落列表 + 输出路径规则 + frontmatter）
  MdAssembler = 统一装配器（注册模板 → assemble → 写入文件）

架构优势：
  - 模板独立定义，互不干扰，方便管理/阅读/扩展
  - 渲染器函数可复用（通用 kv/list/text 渲染器）
  - 新增 MD 类型只需注册新模板，不改引擎代码
  - Section.condition 支持"有数据才渲染"模式
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 核心数据类型
# ══════════════════════════════════════════════════════════


@dataclass
class MdSection:
    """
    MD 文档的一个渲染段落。

    key:         从 data dict 中取哪个 key
    title:       段落标题（如 "## 📋 总结"），空字符串不显示标题
    renderer:    渲染函数 (value, data, **kwargs) -> List[str]
    kv_map:      render_kv_section 的 key→label 映射
    condition:   条件函数 (data) -> bool，False 跳过此段落
    """

    key: str
    title: str
    renderer: Callable
    kv_map: list[tuple[str, str]] | None = None
    condition: Callable[[dict], bool] | None = None


@dataclass
class MdTemplate:
    """
    一份完整的 MD 文档模板定义。

    template_id:        唯一标识，如 "daily_report"
    title_builder:      (data) -> str  标题行
    output_path_rule:   (vault_root, data) -> Path  输出路径
    sections:           渲染段落列表
    frontmatter_builder: (data) -> dict | str  YAML frontmatter
    header_lines:       (data) -> List[str]  标题后固定行
    footer_lines:       (data) -> List[str]  文档末尾固定行
    """

    template_id: str
    title_builder: Callable[[dict], str]
    output_path_rule: Callable[[Path, dict], Path]
    sections: list[MdSection] = field(default_factory=list)
    frontmatter_builder: Callable[[dict], Any] | None = None
    header_lines: Callable[[dict], list[str]] | None = None
    footer_lines: Callable[[dict], list[str]] | None = None


# ══════════════════════════════════════════════════════════
# 内置渲染器（可复用的"零件"）
# ══════════════════════════════════════════════════════════


def render_text(value: Any, data: dict, **kwargs) -> list[str]:
    """纯文本段落（兼容 value 为整个 report_data dict：取其 summary 字段）"""
    if isinstance(value, dict):
        value = value.get("summary") or value.get("text") or ""
    if not value:
        return []
    return [str(value), ""]


def render_kv(value: Any, data: dict, kv_map=None, **kwargs) -> list[str]:
    """
    key-value 段落。遍历 kv_map [(key, label), ...]，
    从 value dict 取对应字段输出。
    列表值: **label**:\n- item
    标量值: **label**: value

    v9.10.1 修复：report_data 的子字段多为嵌套 dict（如 experience.deep_dive、
    metrics.productivity_score）。当 value 顶层取不到 key 时，自动下钻一层
    （在 value 的子 dict 中找该 key），使嵌套 section 正确渲染。
    """
    if not value or not isinstance(value, dict) or not kv_map:
        return []

    def _resolve(v: dict, key: str):
        if key in v:
            return v[key]
        # 下钻一层：在子 dict 中查找（当前数据 key 基本唯一，风险低）
        for sub in v.values():
            if isinstance(sub, dict) and key in sub:
                return sub[key]
        return None

    lines = []
    for key, label in kv_map:
        items = _resolve(value, key)
        if items is None:
            continue
        if isinstance(items, list):
            if not items:
                continue
            lines.append(f"**{label}**:")
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append(f"**{label}**: {items}")
    if lines:
        lines.append("")
    return lines


def render_list(value: Any, data: dict, **kwargs) -> list[str]:
    """列表段落：每个元素 - {item}"""
    if not value or not isinstance(value, list):
        return []
    lines = [f"- {item}" for item in value]
    lines.append("")
    return lines


def render_achievements(value: Any, data: dict, **kwargs) -> list[str]:
    """成果段落：- **{achievement}** — {impact}
    v9.10.1 修复：value 为整个 report_data dict 时，取其 key_achievements/
    major_achievements 子字段（list）再渲染。"""
    if isinstance(value, dict):
        value = value.get("key_achievements") or value.get("major_achievements") or []
    if not value or not isinstance(value, list):
        return []
    lines = []
    for item in value:
        if isinstance(item, dict):
            ach = item.get("achievement", "")
            imp = item.get("impact", "")
            lines.append(f"- **{ach}**" + (f" — {imp}" if imp else ""))
        else:
            lines.append(f"- {item}")
    lines.append("")
    return lines


def render_psychology(value: Any, data: dict, kv_map=None, **kwargs) -> list[str]:
    """心理/协作信号：从 report_data['psychology'] 嵌套 dict 取子字段渲染（复用 render_kv）"""
    if not isinstance(value, dict):
        return []
    psy = value.get("psychology") or {}
    if not isinstance(psy, dict):
        return []
    return render_kv(psy, data, kv_map=kv_map)


def render_metrics(value: Any, data: dict, kv_map=None, **kwargs) -> list[str]:
    """指标段落：每个指标为 {score, evidence}（或纯整数），渲染为 `**label**: score — 证据：evidence`

    v9.10.1 新增（P1）：日报 metrics 改为带证据结构，分数不再是无依据的拍脑袋分。
    v9.10.1 修复：assemble 传入整个 report_data dict 作为 value，需先下钻到 metrics 子 dict
    （与 render_achievements / render_project_dimension 一致）。
    """
    if not isinstance(value, dict) or not kv_map:
        return []
    metrics = value.get("metrics") or {}
    if not isinstance(metrics, dict):
        return []
    lines = []
    for key, label in kv_map:
        item = metrics.get(key)
        if item is None:
            continue
        if isinstance(item, dict):
            score = item.get("score")
            evidence = item.get("evidence", "")
        else:
            score = item
            evidence = ""
        if score is None:
            continue
        line = f"**{label}**: {score}"
        if evidence:
            line += f" — 证据：{evidence}"
        lines.append(line)
    if lines:
        lines.append("")
    return lines


def render_user_profile(value: Any, data: dict, **kwargs) -> list[str]:
    """用户画像维度"""
    if not value or not isinstance(value, list):
        return []
    icons = {"rising": "📈", "declining": "📉", "stable": "➡️"}
    lines = []
    for dim in value:
        if not isinstance(dim, dict):
            continue
        d = dim.get("dimension", "")
        v = dim.get("value", "")
        c = dim.get("confidence", 0)
        t = dim.get("trend", "stable")
        e = dim.get("evidence", "")
        icon = icons.get(t, "➡️")
        lines.extend(
            [
                f"### {d}",
                f"- **值**: {v}",
                f"- **置信度**: {c:.0%}",
                f"- **趋势**: {icon} {t}",
            ]
        )
        if e:
            lines.append(f"- **证据**: {e}")
        lines.append("")
    return lines


def render_project_dimension(value: Any, data: dict, **kwargs) -> list[str]:
    """项目维度段落（日报中的项目归纳）
    v9.10.1 修复：value 为整个 report_data dict 时，取其 project_analysis.projects 子字段。"""
    if isinstance(value, dict):
        value = (value.get("project_analysis") or {}).get("projects") or []
    if not value or not isinstance(value, list):
        return []
    lines = ["> 以下为今日各项目的简要归纳，完整分析见项目仪表盘。", ""]
    for p in value:
        pname = p.get("project_name", "未命名项目")
        safe = re.sub(r'[<>:"/\\|?*]', "-", pname).strip()
        lines.append(f"### 📁 {pname}")
        lines.append("")

        ws = p.get("work_summary", "")
        if ws:
            lines.append(f"**今日工作**: {ws}")
            lines.append("")

        bugs_found = p.get("bugs_found", [])
        bugs_fixed = p.get("bugs_fixed", [])
        if bugs_found or bugs_fixed:
            lines.append("**Bug 情况**:")
            lines.append("")
            if bugs_found:
                lines.append("| 分类 | 描述 | 状态 |")
                lines.append("|------|------|------|")
                for bug in bugs_found:
                    lines.append(
                        f"| {bug.get('category', '')} | {bug.get('description', '')} | 发现 |"
                    )
            if bugs_fixed:
                if not bugs_found:
                    lines.append("| 分类 | 描述 | 状态 |")
                    lines.append("|------|------|------|")
                for bf in bugs_fixed:
                    lines.append(f"| — | {bf.get('description', '')} | ✅ 已修复 |")
            lines.append("")

        kf = p.get("key_files", [])
        if kf:
            s = "、".join(f"`{f}`" for f in kf[:6])
            s += f" 等{len(kf)}个文件" if len(kf) > 6 else ""
            lines.append(f"**文件变更**: {s}")
            lines.append("")

        kfb = p.get("knowledge_for_base", [])
        if kfb:
            lines.append("**知识落地**:")
            lines.append("")
            for kb in kfb:
                title = kb.get("title", "")
                tags = kb.get("tags", [])
                tag_str = " ".join(f"`#{t}`" for t in tags)
                domain = tags[0] if tags else "通用"
                lines.append(f"- [[Cards/{domain}/{title}]] {tag_str}")
                ct = kb.get("content", "")
                if ct:
                    lines.append(f"  > {ct[:120]}{'...' if len(ct) > 120 else ''}")
            lines.append("")

        dec = p.get("decisions", [])
        if dec:
            lines.append("**技术决策**:")
            lines.append("")
            for d in dec:
                lines.append(f"- {d}")
            lines.append("")

        lines.append(f"→ 详见 [[Efforts/{safe}/项目仪表盘]]")
        lines.append("")
    return lines


# ══════════════════════════════════════════════════════════
# 统一装配器
# ══════════════════════════════════════════════════════════


class MdAssembler:
    """MD 文档统一装配器。注册模板 → 传入数据 → 装配 MD → 写入文件。"""

    def __init__(self, vault_root: str = None):
        if vault_root:
            self._vault_root = Path(vault_root)
        else:
            import os

            self._vault_root = Path(
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                    "data",
                    "Knowledge Library",
                )
            )
        self._vault_root.mkdir(parents=True, exist_ok=True)
        self._templates: dict[str, MdTemplate] = {}

    @property
    def vault_root(self) -> Path:
        return self._vault_root

    def register(self, template: MdTemplate):
        self._templates[template.template_id] = template
        logger.debug(f"📝 MD 模板已注册: {template.template_id}")

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())

    def assemble(self, template_id: str, data: dict) -> str | None:
        """装配完整 MD 文档字符串"""
        tpl = self._templates.get(template_id)
        if not tpl:
            logger.error(f"❌ MD 模板未注册: {template_id}")
            return None

        lines = [tpl.title_builder(data), ""]
        if tpl.header_lines:
            lines.extend(tpl.header_lines(data))

        for sec in tpl.sections:
            if sec.condition and not sec.condition(data):
                continue
            value = data.get(sec.key)
            if value is None and sec.condition is None:
                continue

            rendered = sec.renderer(value, data, kv_map=sec.kv_map)
            if not rendered:
                continue
            if sec.title:
                lines.append(sec.title)
                lines.append("")
            lines.extend(rendered)

        if tpl.footer_lines:
            lines.extend(tpl.footer_lines(data))
        return "\n".join(lines)

    def build_frontmatter(self, template_id: str, data: dict) -> str:
        """构建 YAML frontmatter"""
        tpl = self._templates.get(template_id)
        if not tpl or not tpl.frontmatter_builder:
            return ""
        fm = tpl.frontmatter_builder(data)
        if isinstance(fm, str):
            return fm
        if isinstance(fm, dict):
            return self._dict_to_yaml(fm)
        return ""

    def export(self, template_id: str, data: dict) -> str | None:
        """装配 + 写入文件，返回路径"""
        tpl = self._templates.get(template_id)
        if not tpl:
            return None
        file_path = tpl.output_path_rule(self._vault_root, data)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        body = self.assemble(template_id, data)
        if body is None:
            return None
        fm = self.build_frontmatter(template_id, data)
        with open(file_path, "w", encoding="utf-8") as f:
            if fm:
                f.write(fm + "\n\n")
            f.write(body)
        logger.info(f"📝 MD 已导出 [{template_id}]: {file_path}")
        return str(file_path)

    @staticmethod
    def _dict_to_yaml(data: dict) -> str:
        lines = ["---"]
        for k, v in data.items():
            if isinstance(v, str):
                v = v.replace('"', '\\"').replace("\n", "\\n")
                lines.append(f'{k}: "{v}"')
            elif isinstance(v, (int, float)):
                lines.append(f"{k}: {v}")
            elif isinstance(v, list):
                items = ", ".join(f'"{x}"' if isinstance(x, str) else str(x) for x in v)
                lines.append(f"{k}: [{items}]")
            elif isinstance(v, bool):
                lines.append(f"{k}: {'true' if v else 'false'}")
            else:
                lines.append(f'{k}: "{str(v)}"')
        lines.append("---")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_assembler: MdAssembler | None = None


def get_assembler(vault_root: str = None) -> MdAssembler:
    global _assembler
    if _assembler is None:
        _assembler = MdAssembler(vault_root=vault_root)
    return _assembler
