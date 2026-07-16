"""系统交互工具集 - 4个纯函数"""
import subprocess
import platform
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

def execute_system_command(command: str, cwd: str = ".", timeout: int = 60) -> Dict[str, Any]:
    """执行系统命令 - 返回结果，不存储"""
    try:
        result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True,
                               text=True, encoding='utf-8', errors='replace', timeout=timeout)
        success = result.returncode == 0
        
        return {
            "success": success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command,
            "working_directory": cwd,
            "timeout": timeout,
            "error": None if success else f"退出码: {result.returncode}"
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "returncode": -1, "stdout": "", "stderr": f"超时（{timeout}秒）", "error": "超时"}
    except Exception as e:
        return {"success": False, "returncode": -1, "stdout": "", "stderr": str(e), "error": str(e)}

def detect_client(workspace_path: str = "") -> Dict[str, Any]:
    """检测 AI 客户端类型 - 纯检测，无副作用"""
    workspace = Path(workspace_path) if workspace_path else Path.cwd()
    
    client_signatures = {
        "Trae": [".trae", "settings.json"],
        "Cursor": [".cursor", "rules.json"],
        "Windsurf": [".windsurfrules"],
        "CodeBuddy": [".codebuddy", "settings.json"]
    }
    
    detected_clients = []
    for client_name, signatures in client_signatures.items():
        confidence = 0.0
        found_files = []
        for sig in signatures:
            check_path = workspace / sig
            if check_path.exists():
                confidence += 0.5
                found_files.append(str(check_path))
        
        if confidence > 0:
            detected_clients.append({
                "client_name": client_name,
                "confidence": min(confidence, 1.0),
                "config_files": found_files
            })
    
    detected_clients.sort(key=lambda x: x["confidence"], reverse=True)
    best_match = detected_clients[0] if detected_clients else {"client_name": "unknown", "confidence": 0.0, "config_files": []}
    
    return {
        "success": True,
        "detected_client": best_match,
        "all_candidates": detected_clients,
        "workspace": str(workspace),
        "error": None
    }

def environment_scan() -> Dict[str, Any]:
    """完整环境扫描 - 只读操作"""
    info = {
        "timestamp": datetime.now().isoformat(),
        "operating_system": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "workspace": {"current_directory": os.getcwd(), "user": os.getenv('USERNAME') or os.getenv('USER')},
        "tools_available": {},
        "disk_usage": None
    }
    
    # 检测工具
    for tool, cmd in [("git", ["git", "--version"]), ("nodejs", ["node", "--version"]), ("docker", ["docker", "--version"])]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=5)
            info["tools_available"][tool] = {"installed": r.returncode == 0, "version": r.stdout.strip() if r.returncode == 0 else None}
        except:
            info["tools_available"][tool] = {"installed": False, "version": None}
    
    # 磁盘空间
    try:
        du = shutil.disk_usage(Path.cwd())
        info["disk_usage"] = {"total_gb": round(du.total / (1024**3), 2), "free_gb": round(du.free / (1024**3), 2)}
    except:
        pass
    
    return {"success": True, "environment_info": info, "error": None}

def validate_path(path: str) -> Dict[str, Any]:
    """验证路径可用性 - 安全检查"""
    p = Path(path)
    
    result = {"path": str(p), "exists": p.exists(), "valid": False, "type": None, "permissions": {}, "error": None}
    
    if not p.exists():
        result["error"] = f"路径不存在: {path}"
        return result
    
    if p.is_file(): result["type"], result["valid"] = "file", True
    elif p.is_dir(): result["type"], result["valid"] = "directory", True
    elif p.is_symlink(): result["type"], result["valid"] = "symlink", True; result["resolved"] = str(p.resolve())
    else:
        result["type"] = "unknown"
        result["error"] = f"未知类型: {path}"
        return result
    
    result["permissions"] = {"readable": os.access(path, os.R_OK), "writable": os.access(path, os.W_OK)}
    if not result["permissions"]["readable"]:
        result["valid"] = False
        result["error"] = "不可读"
    
    return result

def register_system_tools(mcp):
    """注册系统工具到 MCP"""

    @mcp.tool()
    def execute_system_command_tool(command: str, cwd: str = ".", timeout: int = 60) -> str:
        """执行系统命令。"""
        import json as _json
        return _json.dumps(execute_system_command(command, cwd, timeout), ensure_ascii=False, default=str)

    @mcp.tool()
    def detect_client_tool(workspace_path: str = "") -> str:
        """检测客户端环境。"""
        import json as _json
        return _json.dumps(detect_client(workspace_path), ensure_ascii=False, default=str)

    @mcp.tool()
    def environment_scan_tool() -> str:
        """扫描运行环境。"""
        import json as _json
        return _json.dumps(environment_scan(), ensure_ascii=False, default=str)

    @mcp.tool()
    def validate_path_tool(path: str) -> str:
        """验证路径安全性。"""
        import json as _json
        return _json.dumps(validate_path(path), ensure_ascii=False, default=str)
