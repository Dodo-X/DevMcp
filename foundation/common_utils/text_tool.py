"""文本通用工具。"""


def truncate(text: str | None, limit: int, suffix: str = "…") -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + suffix
