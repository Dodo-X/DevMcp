import os
import re


def find_unused_methods():
    project_root = r"D:\WorkSpace\Code\devPartner"
    py_files = []

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache", ".git")]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

    functions = {}
    for filepath in py_files:
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            matches = re.findall(r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", content, re.MULTILINE)
            for func_name in matches:
                if func_name not in functions:
                    functions[func_name] = []
                functions[func_name].append(filepath)
        except Exception as e:
            print(f"Error reading {filepath}: {e}")

    all_content = ""
    for filepath in py_files:
        try:
            with open(filepath, encoding="utf-8") as f:
                all_content += f.read() + "\n"
        except Exception:
            pass

    unused_funcs = []
    for func_name, locations in functions.items():
        pattern = r"[^a-zA-Z0-9_]" + re.escape(func_name) + r"[^a-zA-Z0-9_]"
        if not re.search(pattern, all_content):
            unused_funcs.append((func_name, locations))

    print("=== 未被使用的方法清单 ===")
    print(f"共发现 {len(unused_funcs)} 个未被调用的方法")
    print("-" * 80)
    for func_name, locations in sorted(unused_funcs, key=lambda x: x[0]):
        print(f"\n方法名: {func_name}")
        print("所在文件:")
        for loc in locations:
            print(f"  - {loc}")


if __name__ == "__main__":
    find_unused_methods()
