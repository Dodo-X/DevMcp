# md_render —— MD 导出静态模板（预留）

当前 MD 导出模板以 Python 代码形式集中在
`backend/business/vault_export/md_templates.py`（配合 `md_engine.py` 装配）。

本目录用于后续将模板抽离为纯占位符的静态 `.tpl.md` 文件，例如：

```
knowledge_card/*.tpl.md
project_profile.tpl.md
user_profile.tpl.md
knowledge_summary.tpl.md
```

抽离后 `md_templates.py` 仅负责读取模板并填充，实现「模板与代码分离」。
