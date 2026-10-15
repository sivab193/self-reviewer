from __future__ import annotations

import re
from dataclasses import dataclass

MARKER_NAME = "aayvu-open-code-review"
MARKER_RE = re.compile(r"<!--\s*aayvu-open-code-review\s*\n(?P<body>.*?)-->", re.DOTALL)
SAFE_VALUE = re.compile(r"^[^\r\n<>]*$")


@dataclass(frozen=True)
class ReviewState:
    schema: str
    status: str
    head_sha: str
    config_sha256: str
    model: str
    model_revision: str
    ocr_version: str
    run_id: str

    def complete_for(self, head_sha: str, config_hash: str, model_revision: str, ocr_version: str,
                     accept_previous_config: bool = False) -> bool:
        return (self.status == "complete" and self.head_sha == head_sha
                and (accept_previous_config or self.config_sha256 == config_hash)
                and self.model_revision == model_revision and self.ocr_version == ocr_version)


def parse_marker(text: str) -> ReviewState | None:
    matches = list(MARKER_RE.finditer(text))
    if not matches:
        return None
    values: dict[str, str] = {}
    for line in matches[-1].group("body").splitlines():
        if "=" in line:
            key, value = line.strip().split("=", 1)
            values[key] = value
    try:
        return ReviewState(**values)
    except TypeError:
        return None


def render_marker(state: ReviewState) -> str:
    values = state.__dict__
    if any(not SAFE_VALUE.fullmatch(str(value)) for value in values.values()):
        raise ValueError("unsafe state marker value")
    rows = "\n".join(f"{key}={value}" for key, value in values.items())
    return f"<!-- {MARKER_NAME}\n{rows}\n-->"


def latest_state(comments: list[dict], trusted_author: str | None = None) -> ReviewState | None:
    candidates = [parse_marker(str(c.get("body", ""))) for c in comments
                  if trusted_author is None or c.get("user", {}).get("login") == trusted_author]
    valid = [candidate for candidate in candidates if candidate]
    return valid[-1] if valid else None

