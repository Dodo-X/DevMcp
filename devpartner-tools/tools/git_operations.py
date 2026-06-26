"""Git 操作工具集 - 3个纯函数"""
import subprocess
from typing import Dict, Any

def git_status(repo_path: str = ".") -> Dict[str, Any]:
    """查看 Git 仓库状态 - 纯查询，无副作用"""
    try:
        result = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return {"success": False, "error": f"Git 命令失败: {result.stderr}", "is_git_repo": False}
        
        staged, modified, untracked = [], [], []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            status = line[:2]
            file_path = line[3:]
            
            if status[0] in ['M', 'A', 'D', 'R', 'C']:
                staged.append(file_path)
            if status[1] in ['M', 'D']:
                modified.append(file_path)
            if status == '??':
                untracked.append(file_path)
        
        branch_result = subprocess.run(["git", "branch", "--show-current"], cwd=repo_path, capture_output=True, text=True, timeout=10)
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
        
        is_clean = len(staged) == 0 and len(modified) == 0 and len(untracked) == 0
        
        return {
            "success": True,
            "branch": branch,
            "staged": staged,
            "modified": modified,
            "untracked": untracked,
            "is_clean": is_clean,
            "is_git_repo": True,
            "error": None
        }
    except FileNotFoundError:
        return {"success": False, "error": "Git 未安装", "is_git_repo": False}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Git 超时", "is_git_repo": True}
    except Exception as e:
        return {"success": False, "error": str(e), "is_git_repo": False}

def git_log(repo_path: str = ".", limit: int = 10) -> Dict[str, Any]:
    """查看 Git 提交历史 - 纯查询"""
    try:
        result = subprocess.run(
            ["git", "log", f"-{limit}", "--pretty=format:%H|%an|%s|%ai"],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            return {"success": False, "commits": [], "error": result.stderr}
        
        commits = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0][:7],
                    "author": parts[1],
                    "message": parts[2],
                    "date": parts[3]
                })
        
        return {"success": True, "commits": commits, "count": len(commits), "error": None}
    except Exception as e:
        return {"success": False, "commits": [], "error": str(e)}

def git_diff(repo_path: str = ".", staged: bool = False) -> Dict[str, Any]:
    """查看 Git 差异 - 纯查询"""
    try:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")
        
        result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=30)
        
        stats_result = subprocess.run(["git", "diff", "--stat"] + (["--cached"] if staged else []),
                                      cwd=repo_path, capture_output=True, text=True, timeout=10)
        
        return {
            "success": True,
            "diff": result.stdout,
            "stats": stats_result.stdout if stats_result.returncode == 0 else "",
            "staged": staged,
            "has_changes": len(result.stdout.strip()) > 0,
            "error": None
        }
    except Exception as e:
        return {"success": False, "diff": "", "error": str(e)}
