"""
思维导图生成服务
- Mermaid mindmap 格式生成
- 思维导图模板
- HTML 可视化输出
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


class MindMapService:
    """思维导图生成服务"""

    _instance: Optional["MindMapService"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._output_dir = Path("data/mindmaps")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    def generate_mermaid(self, title: str, nodes: dict, 
                         direction: str = "TB") -> str:
        """
        生成 Mermaid mindmap 代码
        
        参数:
            title: 根节点标题
            nodes: 节点树，格式: {"name": "节点名", "children": [...], "shape": "rounded|cloud|square"}
            direction: 方向 TB(上到下) / LR(左到右)
        """
        lines = ["mindmap"]
        lines.append(f"  root[{title}]")

        def _render_children(children: list, indent: int, prefix: str = ""):
            for child in children:
                name = child.get("name", "未命名")
                shape = child.get("shape", "")
                indent_str = "  " * indent

                if shape == "cloud":
                    node_text = f"){name}("
                elif shape == "rounded":
                    node_text = f"({name})"
                elif shape == "bang":
                    node_text = f")){name}(("
                elif shape == "hexagon":
                    node_text = f"{{{{{name}}}}}"
                else:
                    node_text = f"[{name}]"

                lines.append(f"{indent_str}{prefix}{node_text}")
                
                if "children" in child:
                    _render_children(child["children"], indent + 1)

        if "children" in nodes:
            _render_children(nodes["children"], 1)

        return "\n".join(lines)

    def generate_from_data(self, title: str, data: dict) -> str:
        """
        从结构化数据生成思维导图
        
        data 格式:
        {
            "categories": [
                {
                    "name": "分类1",
                    "items": ["项1", "项2"],
                    "subcategories": [
                        {"name": "子分类", "items": [...]}
                    ]
                }
            ]
        }
        """
        lines = ["mindmap"]
        lines.append(f"  root(({title}))")

        categories = data.get("categories", [])
        for cat in categories:
            cat_name = cat.get("name", "未命名")
            lines.append(f"    {cat_name}")

            items = cat.get("items", [])
            for item in items:
                if isinstance(item, str):
                    lines.append(f"      [{item}]")
                elif isinstance(item, dict):
                    item_name = item.get("name", str(item))
                    lines.append(f"      [{item_name}]")

            subcategories = cat.get("subcategories", [])
            for sub in subcategories:
                sub_name = sub.get("name", "")
                lines.append(f"      {sub_name}")
                for sub_item in sub.get("items", []):
                    lines.append(f"        [{sub_item}]")

        return "\n".join(lines)

    def generate_ai_analysis(self, topic: str, content: str) -> str:
        """
        使用 AI 分析内容并生成思维导图
        (需要 Ollama 服务)
        """
        # 作为异步函数的同步包装，这里先返回模板
        prompt = f"""
请分析以下内容并生成思维导图 Mermaid 代码：

主题：{topic}
内容：{content}

格式要求（严格只输出 mermaid 代码块）：
```mermaid
mindmap
  root(({topic}))
    分支1
      子项
    分支2
      子项
```
"""
        return prompt  # 实际调用需要异步，这里返回提示词供服务层调用

    def save_mindmap(self, title: str, mermaid_code: str, 
                     format: str = "mermaid") -> str:
        """保存思维导图到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:50]

        if format == "mermaid":
            filename = f"mindmap_{safe_title}_{timestamp}.md"
            filepath = self._output_dir / filename

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                f.write("```mermaid\n")
                f.write(mermaid_code)
                f.write("\n```\n")

        elif format == "html":
            filename = f"mindmap_{safe_title}_{timestamp}.html"
            filepath = self._output_dir / filename

            html = self._generate_html(title, mermaid_code)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)

        else:
            filename = f"mindmap_{safe_title}_{timestamp}.txt"
            filepath = self._output_dir / filename
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(mermaid_code)

        # 记录到数据库
        try:
            from core.database import get_db
            db = get_db()
            db.query_local(
                """INSERT INTO mindmaps (timestamp, title, topic, format, content, file_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.now().isoformat(), title, title, format, mermaid_code, str(filepath)),
            )
        except Exception:
            pass

        return str(filepath)

    def _generate_html(self, title: str, mermaid_code: str) -> str:
        """生成包含 Mermaid 渲染的 HTML 页面"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - 思维导图</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 30px;
        }}
        h1 {{
            text-align: center;
            color: #333;
            margin-bottom: 20px;
            font-size: 28px;
        }}
        .mermaid {{
            display: flex;
            justify-content: center;
            overflow: auto;
            padding: 20px;
        }}
        .footer {{
            text-align: center;
            color: #999;
            margin-top: 20px;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🧠 {title}</h1>
        <div class="mermaid">
{mermaid_code}
        </div>
    </div>
    <div class="footer">
        Generated by devPartner | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
    </script>
</body>
</html>"""

    def list_mindmaps(self) -> list[dict]:
        """列出所有生成的思维导图"""
        mindmaps = []
        if self._output_dir.exists():
            for f in sorted(self._output_dir.glob("mindmap_*"), reverse=True):
                mindmaps.append({
                    "filename": f.name,
                    "path": str(f),
                    "size_bytes": f.stat().st_size,
                    "created": datetime.fromtimestamp(f.stat().st_ctime).isoformat(),
                })
        return mindmaps

    def get_mindmap_preview(self, filename: str) -> str:
        """获取思维导图内容预览"""
        filepath = self._output_dir / filename
        if not filepath.exists():
            return json.dumps({"error": "文件不存在"}, ensure_ascii=False)

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        return json.dumps({
            "filename": filename,
            "content": content,
            "size": len(content),
        }, ensure_ascii=False)


def get_mindmap() -> MindMapService:
    return MindMapService()
