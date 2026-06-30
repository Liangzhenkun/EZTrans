from __future__ import annotations

import re
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def looks_like_single_term(value: str) -> bool:
    trimmed = value.strip()
    if not trimmed:
        return False
    if len(trimmed) > 48:
        return False
    if any(ch in trimmed for ch in ".!?;,，。！？；：:\n"):
        return False
    if re.search(r"[\u4e00-\u9fff]", trimmed):
        return len(trimmed) <= 16
    tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'-]*", trimmed)
    return 1 <= len(tokens) <= 5


def chunk_text(value: str, size: int = 400) -> list[str]:
    cleaned = value.strip()
    if len(cleaned) <= size:
        return [cleaned]
    parts: list[str] = []
    while cleaned:
        parts.append(cleaned[:size])
        cleaned = cleaned[size:]
    return parts


def extract_search_terms(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    if re.search(r"[\u4e00-\u9fff]", text):
        chunks = [part for part in re.findall(r"[\u4e00-\u9fff]{1,4}", text) if len(part) >= 2]
        return list(dict.fromkeys(chunks))[:6]
    parts = [part.lower() for part in re.findall(r"[a-zA-Z][a-zA-Z'-]{1,}", text)]
    filtered = [part for part in parts if len(part) >= 3]
    return list(dict.fromkeys(filtered))[:8]
