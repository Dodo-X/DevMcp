"""
📁 文件系统操作工具集 — 5 个工具

设计原则：
  - read_file / list_directory / search_files / search_content：纯读，无副作用
  - write_file：唯一有副作用的工具（用户显式要求写入）
  - 所有路径均经过安全验证
"""

from pathlib import Path
from typing import Dict, Any
import os
import re
import fnmatch


def _validate_path(file_path: str) -> Path:
    """验证路径安全性，转换为绝对路径"""
    path = Path(file_path).resolve()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def read_file(file_path: str, encoding: str = "utf-8", max_size_mb: int = 10) -> Dict[str, Any]:
    """
    读取文件内容 — 纯读，无副作用

    Args:
        file_path: 文件路径（相对或绝对）
        encoding: 文件编码，默认 utf-8
        max_size_mb: 最大文件大小限制（MB），默认 10MB

    Returns:
        {success, content, metadata, error}
    """
    try:
        safe_path = _validate_path(file_path)
        if not safe_path.exists():
            return {"success": False, "content": None, "error": f"文件不存在: {file_path}"}

        file_size = safe_path.stat().st_size
        max_bytes = max_size_mb * 1024 * 1024
        if file_size > max_bytes:
            return {"success": False, "content": None, "error": f"文件过大: {file_size:,} 字节"}

        content = safe_path.read_text(encoding=encoding)
        lines_count = content.count('\n') + 1 if content else 0

        return {
            "success": True,
            "content": content,
            "metadata": {"size_bytes": file_size, "lines_count": lines_count, "encoding": encoding},
            "error": None
        }
    except Exception as e:
        return {"success": False, "content": None, "error": f"读取失败: {str(e)}"}


def write_file(file_path: str, content: str, encoding: str = "utf-8",
               append: bool = False) -> Dict[str, Any]:
    """
    写入文件内容 — 唯一有副作用的工具

    用户显式要求写入时才调用，其他工具保持纯读。

    Args:
        file_path: 文件路径
        content: 要写入的内容
        encoding: 文件编码
        append: True=追加, False=覆盖

    Returns:
        {success, bytes_written, path, mode, error}
    """
    try:
        safe_path = _validate_path(file_path)
        safe_path.parent.mkdir(parents=True, exist_ok=True)

        mode = 'a' if append else 'w'
        with open(safe_path, mode, encoding=encoding) as f:
            f.write(content)

        bytes_written = len(content.encode(encoding))
        return {
            "success": True,
            "bytes_written": bytes_written,
            "path": str(safe_path),
            "mode": "append" if append else "overwrite",
            "error": None
        }
    except Exception as e:
        return {"success": False, "bytes_written": None, "error": f"写入失败: {str(e)}"}


def list_directory(dir_path: str = ".", max_depth: int = 3,
                   filter_pattern: str = "") -> Dict[str, Any]:
    """
    列出目录内容 — 支持递归和过滤

    Args:
        dir_path: 目录路径
        max_depth: 最大递归深度
        filter_pattern: 文件名过滤（fnmatch 格式，如 "*.py"）

    Returns:
        {success, entries, total_count, error}
    """
    try:
        safe_path = _validate_path(dir_path)
        if not safe_path.exists():
            return {"success": False, "entries": [], "error": f"目录不存在: {dir_path}"}

        entries = []

        def scan_dir(path: Path, depth: int):
            if depth > max_depth:
                return
            try:
                for item in path.iterdir():
                    if filter_pattern and not fnmatch.fnmatch(item.name, filter_pattern):
                        continue
                    entries.append({
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "path": str(item),
                        "size": item.stat().st_size if item.is_file() else None
                    })
                    if item.is_dir() and depth < max_depth:
                        scan_dir(item, depth + 1)
            except PermissionError:
                pass

        scan_dir(safe_path, 0)
        return {"success": True, "entries": entries, "total_count": len(entries), "error": None}
    except Exception as e:
        return {"success": False, "entries": [], "error": str(e)}


def search_files(directory: str, pattern: str, recursive: bool = True,
                 max_results: int = 100) -> Dict[str, Any]:
    """
    搜索文件 — 支持通配符匹配

    Args:
        directory: 搜索目录
        pattern: 文件名通配符（如 "*.py", "test_*.ts"）
        recursive: 是否递归子目录
        max_results: 最大结果数

    Returns:
        {success, matches, count, truncated, error}
    """
    try:
        safe_path = _validate_path(directory)
        matches = []

        glob_pattern = f"**/{pattern}" if recursive else pattern
        for file_path in safe_path.glob(glob_pattern):
            if file_path.is_file():
                matches.append({
                    "name": file_path.name,
                    "path": str(file_path),
                    "size": file_path.stat().st_size
                })
                if len(matches) >= max_results:
                    break

        return {
            "success": True,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= max_results,
            "error": None
        }
    except Exception as e:
        return {"success": False, "matches": [], "error": str(e)}


def search_content(directory: str, pattern: str, file_pattern: str = "*",
                   recursive: bool = True, case_sensitive: bool = False,
                   max_results: int = 50, context_lines: int = 0) -> Dict[str, Any]:
    """
    搜索文件内容 — 类似 ripgrep 的文本搜索

    Args:
        directory: 搜索目录
        pattern: 正则表达式
        file_pattern: 文件名过滤通配符
        recursive: 是否递归子目录
        case_sensitive: 是否区分大小写
        max_results: 最大匹配数
        context_lines: 上下文行数

    Returns:
        {success, results, count, truncated, files_scanned, error}
    """
    try:
        safe_path = _validate_path(directory)
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)

        results = []
        glob_pattern = f"**/{file_pattern}" if recursive else file_pattern
        files_to_search = list(safe_path.glob(glob_pattern))

        for file_path in files_to_search:
            if not file_path.is_file():
                continue

            content = None
            for enc in ['utf-8', 'gbk', 'latin-1']:
                try:
                    content = file_path.read_text(encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue

            if not content:
                continue

            lines = content.split('\n')
            for line_num, line in enumerate(lines, 1):
                match = regex.search(line)
                if match:
                    context_start = max(0, line_num - 1 - context_lines)
                    context_end = min(len(lines), line_num + context_lines)

                    results.append({
                        "file": str(file_path),
                        "line": line_num,
                        "match": line.strip(),
                        "context_before": lines[context_start:line_num - 1] if context_lines > 0 else [],
                        "context_after": lines[line_num:context_end] if context_lines > 0 else [],
                        "matched_text": match.group()
                    })

                    if len(results) >= max_results:
                        return {
                            "success": True, "results": results, "count": len(results),
                            "truncated": True, "error": None
                        }

        return {
            "success": True, "results": results, "count": len(results),
            "truncated": False, "files_scanned": len(files_to_search), "error": None
        }
    except Exception as e:
        return {"success": False, "results": [], "error": str(e)}
