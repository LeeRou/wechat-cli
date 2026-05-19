"""输出格式化 — JSON (大模型友好) / Text (人类可读)"""

import json
import sys


def _ensure_utf8():
    """确保 stdout/stderr 使用 UTF-8 编码 (Windows GBK 无法输出 emoji 等字符)"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


_ensure_utf8()


def output_json(data, file=None):
    file = file or sys.stdout
    json.dump(data, file, ensure_ascii=False, indent=2)
    file.write("\n")


def output_text(text, file=None):
    file = file or sys.stdout
    file.write(text)
    if not text.endswith("\n"):
        file.write("\n")


def output(data, fmt="json", file=None):
    if fmt == "json":
        output_json(data, file)
    else:
        if isinstance(data, str):
            output_text(data, file)
        elif isinstance(data, dict) and "text" in data:
            output_text(data["text"], file)
        else:
            output_json(data, file)
