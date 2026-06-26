"""
原生 Python 工具实现
- Git 操作（直接调 git 命令）
- URL 请求（httpx）
- SQLite 查询
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def git_status(repo_path: str = ".") -> str:
    """获取 Git 仓库状态 - 直接调用 git 命令"""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=15,
        )
        changes = []
        staged = []
        untracked = []

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            status = line[:2]
            file_path = line[3:]
            if status[0] != " " and status[0] != "?":
                staged.append({"status": status, "file": file_path})
            elif status[1] != " ":
                changes.append({"status": status, "file": file_path})
            else:
                untracked.append({"status": status, "file": file_path})

        return json.dumps({
            "success": True,
            "repo": os.path.abspath(repo_path),
            "staged": staged,
            "changed": changes,
            "untracked": untracked,
            "total_changes": len(staged) + len(changes) + len(untracked),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def git_log(repo_path: str = ".", limit: int = 10, format: str = "oneline") -> str:
    """获取 Git 提交历史"""
    try:
        fmt_map = {
            "oneline": "--oneline",
            "full": "--format=%H|%an|%ae|%ai|%s",
            "short": "--format=%h %ai %s",
        }
        fmt_arg = fmt_map.get(format, "--oneline")

        if format == "oneline":
            result = subprocess.run(
                ["git", "-C", repo_path, "log", "--oneline", f"-{limit}"],
                capture_output=True, text=True, timeout=15,
            )
            commits = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(" ", 1)
                    commits.append({
                        "hash": parts[0] if len(parts) > 0 else "",
                        "message": parts[1] if len(parts) > 1 else line,
                    })
        else:
            result = subprocess.run(
                ["git", "-C", repo_path, "log", fmt_arg, f"-{limit}"],
                capture_output=True, text=True, timeout=15,
            )
            commits = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("|")
                    if len(parts) >= 5:
                        commits.append({
                            "hash": parts[0],
                            "author": parts[1],
                            "email": parts[2],
                            "date": parts[3],
                            "message": parts[4],
                        })

        return json.dumps({
            "success": True,
            "commits": commits,
            "count": len(commits),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def git_diff(repo_path: str = ".", staged: bool = False) -> str:
    """获取 Git diff"""
    try:
        cmd = ["git", "-C", repo_path, "diff"]
        if staged:
            cmd.append("--staged")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        return json.dumps({
            "success": True,
            "has_changes": bool(result.stdout.strip()),
            "diff": result.stdout[:10000],  # 限制输出大小
            "full_length": len(result.stdout),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def fetch_url(url: str, method: str = "GET", headers: str = "{}",
              body: str = "", timeout: int = 30) -> str:
    """获取 URL 内容 - 使用 httpx"""
    try:
        import httpx
        parsed_headers = json.loads(headers) if headers else {}

        if method.upper() == "GET":
            resp = httpx.get(url, headers=parsed_headers, timeout=timeout, follow_redirects=True)
        elif method.upper() == "POST":
            resp = httpx.post(url, headers=parsed_headers, content=body, timeout=timeout)
        else:
            resp = httpx.request(method.upper(), url, headers=parsed_headers, content=body, timeout=timeout)

        result = {
            "success": True,
            "url": str(resp.url),
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "content_type": resp.headers.get("content-type", ""),
        }

        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            result["data"] = resp.json()
        else:
            text = resp.text[:50000]  # 限制 50KB
            result["text"] = text
            result["text_length"] = len(resp.text)
            if len(resp.text) > 50000:
                result["truncated"] = True

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def db_query(sql: str, db_path: str = "", params: list = None) -> str:
    """
    执行 SQL 查询 - 原生 sqlite3
    支持多个数据库路径
    """
    try:
        if not db_path:
            # 默认使用共享数据库
            db_path = "D:/trae-archive/toptown_tracker/work_tracker.db"

        db_file = Path(db_path)
        if not db_file.exists():
            return json.dumps({"error": f"数据库不存在: {db_path}"}, ensure_ascii=False)

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        sql_upper = sql.strip().upper()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        if sql_upper.startswith("SELECT") or sql_upper.startswith("PRAGMA") or sql_upper.startswith("EXPLAIN"):
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return json.dumps({
                "success": True,
                "rows": rows,
                "count": len(rows),
                "db_path": str(db_file),
            }, ensure_ascii=False)
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return json.dumps({
                "success": True,
                "affected_rows": affected,
                "last_id": cursor.lastrowid,
                "db_path": str(db_file),
            }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def sequential_think(thought: str, thought_number: int, total_thoughts: int,
                     next_thought_needed: bool = True, is_revision: bool = False,
                     revises_thought: int = 0, branch_from_thought: int = 0,
                     branch_id: str = "", needs_more_thoughts: bool = True) -> str:
    """
    链式思考工具 - 原生 Python 实现
    替代 @modelcontextprotocol/server-sequential-thinking
    """
    return json.dumps({
        "thoughtNumber": thought_number,
        "totalThoughts": total_thoughts,
        "nextThoughtNeeded": next_thought_needed,
        "branches": [branch_id] if branch_id else [],
        "thoughtHistoryLength": thought_number,
    }, ensure_ascii=False)


def save_memory(key: str, value: str) -> str:
    """保存记忆到本地文件"""
    try:
        memory_dir = Path("data/memories")
        memory_dir.mkdir(parents=True, exist_ok=True)

        memory_file = memory_dir / f"{key}.json"
        data = {
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        # 如果已存在，保留历史
        if memory_file.exists():
            with open(memory_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            data["history"] = existing.get("history", [])
            data["history"].append({
                "previous_value": existing.get("value", ""),
                "changed_at": datetime.now().isoformat(),
            })
            # 只保留最近 10 条历史
            data["history"] = data["history"][-10:]

        with open(memory_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return json.dumps({"success": True, "key": key}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_memory(key: str) -> str:
    """获取记忆"""
    try:
        memory_dir = Path("data/memories")
        memory_file = memory_dir / f"{key}.json"

        if not memory_file.exists():
            return json.dumps({"error": f"记忆不存在: {key}"}, ensure_ascii=False)

        with open(memory_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return json.dumps(data, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def list_memories() -> str:
    """列出所有记忆"""
    try:
        memory_dir = Path("data/memories")
        if not memory_dir.exists():
            return json.dumps({"memories": []}, ensure_ascii=False)

        memories = []
        for f in sorted(memory_dir.glob("*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            memories.append({
                "key": data.get("key", f.stem),
                "timestamp": data.get("timestamp", ""),
                "value_preview": str(data.get("value", ""))[:100],
            })

        return json.dumps({"memories": memories, "count": len(memories)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def execute_command(command: str, cwd: str = ".", timeout: int = 60) -> str:
    """执行系统命令"""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            cwd=cwd, shell=True,
        )
        return json.dumps({
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:5000],
            "stdout_length": len(result.stdout),
        }, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"命令超时 ({timeout}s)"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
