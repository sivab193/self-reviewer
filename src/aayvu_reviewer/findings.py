from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .state import MARKER_NAME


class Finding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    line: int = Field(gt=0)
    end_line: int | None = Field(default=None, gt=0)
    side: Literal["RIGHT", "LEFT"] = "RIGHT"
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    category: str = "other"
    title: str = "Finding"
    body: str
    existing_code: str | None = None

    @property
    def fingerprint(self) -> str:
        raw = "\0".join([self.path, str(self.line), str(self.end_line or self.line), self.title.strip().lower(),
                          self.severity, re.sub(r"\s+", " ", self.body.strip()).lower()])
        return hashlib.sha256(raw.encode()).hexdigest()


def parse_ocr_output(payload: dict[str, Any]) -> list[Finding]:
    raw_comments = payload.get("comments", [])
    if not isinstance(raw_comments, list):
        raise ValueError("OCR output comments must be a list")
    findings: list[Finding] = []
    for raw in raw_comments:
        if "body" not in raw and "content" in raw:
            raw = {**raw, "body": raw["content"]}
        if "line" not in raw:
            raw = {**raw, "line": raw.get("start_line") or raw.get("end_line") or raw.get("new_line")}
        findings.append(Finding.model_validate(raw))
    return findings


def changed_lines_from_patch(patch: str) -> set[int]:
    lines: set[int] = set()
    new_line = 0
    for row in patch.splitlines():
        match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", row)
        if match:
            new_line = int(match.group(1)); continue
        if row.startswith("+") and not row.startswith("+++"):
            lines.add(new_line); new_line += 1
        elif row.startswith("-") and not row.startswith("---"):
            continue
        elif not row.startswith("\\"):
            new_line += 1
    return lines


def safe_path(checkout: Path, value: str) -> Path | None:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        return None
    target = checkout.joinpath(*pure.parts)
    try:
        resolved = target.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        return None
    return resolved if resolved.is_relative_to(checkout.resolve()) and not target.is_symlink() else None


def validate_findings(findings: list[Finding], checkout: Path, files: list[dict], max_comments: int = 30,
                      max_body: int = 6000) -> tuple[list[Finding], list[Finding]]:
    changed = {f["filename"]: changed_lines_from_patch(f.get("patch", "")) for f in files}
    accepted: list[Finding] = []
    fallback: list[Finding] = []
    seen: set[str] = set()
    for finding in findings:
        body = finding.body.replace(f"<!-- {MARKER_NAME}", "&lt;!-- neutralized-marker")[:max_body]
        finding = finding.model_copy(update={"body": body})
        if finding.fingerprint in seen:
            continue
        seen.add(finding.fingerprint)
        target = safe_path(checkout, finding.path)
        if target is None or finding.path not in changed:
            continue
        source_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        line_valid = finding.line <= len(source_lines)
        diff_valid = finding.side == "RIGHT" and finding.line in changed[finding.path]
        quote_valid = True
        if finding.existing_code:
            end = finding.end_line or finding.line
            actual = "\n".join(source_lines[finding.line - 1:end]).strip()
            quote_valid = actual == finding.existing_code.strip()
        (accepted if line_valid and diff_valid and quote_valid and len(accepted) < max_comments else fallback).append(finding)
    return accepted, fallback

