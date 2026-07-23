# Obsidian 知识库系统优化报告

> **日期**: 2026-07-23 | **版本**: v2.4

---

## 一、分析结果

### vault_export 模块架构
6 文件三层架构：`md_templates.py`(模板注册) → `md_data_loader.py`(数据装载) → `md_engine.py`(引擎) → `md_exporter.py`/`vault_exporter.py`(导出)。支持 9 种文档类型。

### Knowledge Library 现状
```
data/Knowledge Library/
├── Home.md                    # ❌ 通用 Ideaverse 模板，所有链接断裂
├── Calendar/                  # 4 篇日报（2 篇测试数据 + 1 篇空 + 1 篇实际）
├── Efforts/devPartner/        # 1 个仪表盘（0 数据）
├── Atlas/ Cards/ Reports/     # 空目录，无导航页
```

### 发现的 6 个问题

| # | 问题 | 严重度 | 根源 |
|---|------|--------|------|
| 1 | Wikilink 反斜杠 Bug | 🔴 | `_write_project_dashboard:471` 未 normalize |
| 2 | Home.md 断裂链接 | 🔴 | Ideaverse 模板与 devPartner 不兼容 |
| 3 | 零 MOC 导航页 | 🟡 | 缺少目录索引 |
| 4 | 仪表盘 0 数据 | 🟡 | 日报 `projects:[]` 为空 |
| 5 | 无反向链接 | 🟡 | footer 仅链出，不链入 |
| 6 | 报告目录无索引 | 🟢 | Reports 三级子目录无导航 |

---

## 二、已实施的优化

### A. 代码修复（3 处 Bug）

| 文件 | 行 | 修复内容 |
|------|-----|----------|
| `vault_exporter.py` | 471 | Wikilink 路径 `\` → `/`（Windows→Obsidian 兼容） |
| `md_engine.py` | 245 | 项目名净化 `_` → `-`（与 `_safe_path` 统一） |

### B. 链接增强（4 处）

| 位置 | 改动 |
|------|------|
| 日报 footer | 新增"导航"段：链接到日历索引、报告索引、图谱总览、首页 |
| 日报 footer | 新增"同期报告"段：自动链接到同周/月/年报告 |
| 知识卡片 body | 新增"来源"段：链接到知识摘要 MD |
| 知识卡片 body | 新增"导航"段：链接到卡片索引和首页 |
| 项目仪表盘 | 新增 Dataview 查询段 + 丰富化导航链接 |

### C. 目录结构重组（12 个新增文件）

```
data/Knowledge Library/
├── Home.md                          # ✅ 重写：devPartner 导航中心
├── Calendar/
│   ├── 日历索引.md                   # ✅ MOC：日报 Dataview 索引
│   └── 2026-07-23.md                # ✅ 新增导航链接
├── Cards/
│   └── 知识卡片索引.md                # ✅ MOC：知识卡片 Dataview 索引
├── Efforts/
│   └── 项目索引.md                    # ✅ MOC：项目仪表盘索引
├── Reports/
│   ├── 报告索引.md                    # ✅ MOC：报告中心
│   ├── Weekly/周报索引.md
│   ├── Monthly/月报索引.md
│   └── Annual/年报索引.md
├── Atlas/
│   └── 图谱总览.md                    # ✅ MOC：全局统计
└── .obsidian/
    ├── graph.json                    # ✅ 更新图谱配色
    └── templates/                    # ✅ 3 个快速笔记模板
        ├── 每日日志模板.md
        ├── 知识卡片模板.md
        └── 项目笔记模板.md
```

---

## 三、字段调整建议（不自动实施）

以下建议涉及系统数据绑定逻辑，需你确认后手动实施：

### 建议 1：日报 frontmatter 增加 `week` / `month` 字段

| 字段 | 新增 | 生成逻辑 | 理由 |
|------|------|----------|------|
| `week` | 是 | `datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-W%W")` | Dataview 可按周/月分组日报，无需每次计算 |
| `month` | 是 | `datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m")` | 同上 |

**修改位置**: `md_templates.py:_daily_fm()` 中增加两个字段。

### 建议 2：知识卡片增加 `project` 字段

| 字段 | 调整 | 生成逻辑 | 理由 |
|------|------|----------|------|
| `project` | 新增 | 从当前对话的 `system_id` 或项目名获取 | 知识卡片可按项目分组，实现跨领域卡片归属 |

**修改位置**: `vault_exporter.py:_build_frontmatter()` 中增加 `project` 字段。

### 建议 3：`frustration_level` / 各 score 字段的空值处理

| 当前问题 | 建议 |
|----------|------|
| 空日报输出 `"None"` 字符串（如 `frustration_level: "None"`） | 改为输出 `null` 或不输出该字段 |
| YAML 中 `"None"` 字符串会污染 Dataview 查询 | 在 `_daily_fm()` 中对 `None` 值做过滤 |

**修改位置**: `md_templates.py:_daily_fm()` → `_score()` 返回值过滤。

---

## 四、验证结果

- `pytest tests/test_vault_export.py -v` — **5/5 passed** ✅
- `py_compile` 三个修改文件 — **全部通过** ✅

---

## 五、后续建议

1. **运行一次 `export_all_knowledge`** 触发仪表盘重生成（获得新导航链接）
2. **考虑安装 Obsidian Dataview 插件** — 所有 MOC 页面依赖此插件实现动态索引
3. **添加 `README` 到 Knowledge Library 根目录** — 说明知识库使用约定
4. **考虑为 `related_knowledge_ids` 添加反向链接自动维护** — 当 A 链接 B 时，自动在 B 的 frontmatter 中添加 A 的引用
