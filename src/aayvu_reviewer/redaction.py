from __future__ import annotations

import re

TOKEN_PATTERNS = [
    re.compile(r"\b(?:ghp|github_pat|hf)_[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|token)\s+)[^\s]+"),
]


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", text)
    return text
