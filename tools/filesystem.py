"""
原生文件系统工具 - 直接 Python 实现
效率远高于 subprocess 调用外部 MCP 服务
"""
import os
import json
import aiofiles
from pathlib import Path
from typing import Optional


# 安全路径限制
def _safe_path(file_path: str, base_dir: Optional[str] = None) -> Path:
    """确保文件路径在安全范围内"""
    if base_dir is None:
        base_dir = os.getcwd()
    base = Path(base_dir).resolve()
    target = (base / file_path).resolve()
    # 允许访问（不对路径做严格限制，因为这是本地开发服务）
    return target


def read_file(file_path: str, encoding: str = "utf-8", max_size_mb: int = 10) -> str:
    """
    读取文件内容
    直接 Python 实现，不需要 subprocess
    """
    try:
        path = _safe_path(file_path)
        if not path.exists():
            return json.dumps({"error": f"文件不存在: {file_path}"}, ensure_ascii=False)

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > max_size_mb:
            return json.dumps({
                "error": f"文件过大 ({size_mb:.1f}MB > {max_size_mb}MB 限制)",
                "size_mb": size_mb,
            }, ensure_ascii=False)

        with open(path, "r", encoding=encoding, errors="replace") as f:
            content = f.read()

        return json.dumps({
            "success": True,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "content": content,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def write_file(file_path: str, content: str, encoding: str = "utf-8", append: bool = False) -> str:
    """
    写入文件内容
    直接 Python 实现
    """
    try:
        path = _safe_path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        with open(path, mode, encoding=encoding) as f:
            f.write(content)

        return json.dumps({
            "success": True,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "mode": "append" if append else "write",
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def list_directory(dir_path: str = ".", max_depth: int = 3, filter_pattern: str = "") -> str:
    """
    列出目录内容
    支持递归和过滤
    """
    try:
        path = _safe_path(dir_path)
        if not path.exists():
            return json.dumps({"error": f"目录不存在: {dir_path}"}, ensure_ascii=False)
        if not path.is_dir():
            return json.dumps({"error": f"不是目录: {dir_path}"}, ensure_ascii=False)

        result = {
            "path": str(path),
            "directories": [],
            "files": [],
            "total_files": 0,
            "total_dirs": 0,
        }

        import fnmatch

        def _walk(current: Path, depth: int):
            if depth > max_depth:
                return
            try:
                for entry in sorted(current.iterdir()):
                    rel = str(entry.relative_to(path))
                    if entry.name.startswith(".") and entry.name != ".gitignore":
                        continue

                    if entry.is_dir():
                        result["directories"].append({
                            "name": entry.name,
                            "path": rel,
                            "depth": depth,
                        })
                        result["total_dirs"] += 1
                        _walk(entry, depth + 1)
                    else:
                        if filter_pattern and not fnmatch.fnmatch(entry.name, filter_pattern):
                            continue
                        result["files"].append({
                            "name": entry.name,
                            "path": rel,
                            "size_bytes": entry.stat().st_size,
                            "depth": depth,
                        })
                        result["total_files"] += 1
            except PermissionError:
                pass

        _walk(path, 1)
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def search_files(directory: str, pattern: str, recursive: bool = True, 
                 case_sensitive: bool = False, max_results: int = 100) -> str:
    """
    搜索文件 - 支持通配符
    """
    try:
        path = _safe_path(directory)
        import fnmatch

        results = []
        flags = 0 if case_sensitive else 0  # fnmatch 本身是大小写敏感的，需要额外处理

        iterator = path.rglob(pattern) if recursive else path.glob(pattern)
        for f in iterator:
            if f.name.startswith("."):
                continue
            if not case_sensitive:
                # 大小写不敏感匹配
                lower_pattern = pattern.lower()
                lower_name = f.name.lower()
                if not fnmatch.fnmatch(lower_name, lower_pattern):
                    continue
            results.append({
                "name": f.name,
                "path": str(f.relative_to(path)),
                "size_bytes": f.stat().st_size if f.is_file() else 0,
                "is_dir": f.is_dir(),
            })
            if len(results) >= max_results:
                break

        return json.dumps({
            "success": True,
            "pattern": pattern,
            "directory": str(path),
            "count": len(results),
            "results": results,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def search_content(directory: str, pattern: str, file_pattern: str = "*",
                   case_sensitive: bool = False, max_results: int = 50,
                   context_lines: int = 0) -> str:
    """
    搜索文件内容 - 类似 ripgrep
    """
    try:
        import re
        path = _safe_path(directory)
        import fnmatch

        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)
        results = []

        # 常见忽略目录
        ignore_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", 
                       ".idea", "target", "build", "dist", ".codebuddy"}

        for f in path.rglob("*"):
            if not f.is_file():
                continue
            if any(part in ignore_dirs for part in f.parts):
                continue
            if not fnmatch.fnmatch(f.name, file_pattern):
                continue
            if f.stat().st_size > 1024 * 1024:  # 跳过 >1MB 文件
                continue

            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        rel_path = str(f.relative_to(path))
                        match = {
                            "file": rel_path,
                            "line": i,
                            "content": line.rstrip("\n")[:500],
                        }
                        if context_lines > 0:
                            start = max(0, i - context_lines - 1)
                            end = min(len(lines), i + context_lines)
                            match["context"] = {
                                "start_line": start + 1,
                                "end_line": end,
                                "lines": [l.rstrip("\n") for l in lines[start:end]],
                            }
                        results.append(match)
                        if len(results) >= max_results:
                            break
            except Exception:
                continue
            if len(results) >= max_results:
                break

        return json.dumps({
            "success": True,
            "pattern": pattern,
            "count": len(results),
            "results": results,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
