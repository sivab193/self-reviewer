from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import ModelProfile, RepositoriesConfig
from .discovery import PullCandidate
from .findings import parse_ocr_output, validate_findings
from .git_workspace import trusted_checkout
from .github_client import GitHubClient
from .ocr_runner import run_ocr
from .publisher import publish
from .reporting import atomic_json, pr_artifact_dir
from .state import ReviewState


def review_candidate(candidate: PullCandidate, client: GitHubClient, token: str, config: RepositoriesConfig,
                     profile: ModelProfile, config_hash: str, project_root: Path, run_dir: Path,
                     publish_enabled: bool) -> dict:
    artifact = pr_artifact_dir(run_dir, candidate.repository, candidate.number)
    atomic_json(artifact / "metadata.json", candidate.to_dict())
    repo_entry = next(r for r in config.repositories if r.repository == candidate.repository)
    options = config.resolved(repo_entry)
    files = client.pull_files(candidate.repository, candidate.number)
    if any(int(f.get("changes", 0)) > options.limits.max_changed_lines or int(f.get("size", 0)) > options.limits.max_file_bytes for f in files):
        raise RuntimeError("PR contains a file exceeding configured size limits")
    with trusted_checkout(candidate.repository, candidate.base, candidate.head_sha, token) as (checkout, merge_base):
        for file in files:
            target = checkout / file["filename"]
            if target.exists() and target.is_file() and target.stat().st_size > options.limits.max_file_bytes:
                raise RuntimeError(f"file exceeds byte limit: {file['filename']}")
        payload = run_ocr(checkout, merge_base, candidate.head_sha, (project_root / candidate.rules).resolve(),
                          artifact / "ocr-result.json", f"http://{profile.host}:{profile.port}/v1/chat/completions",
                          profile.served_model_name, options.ocr.timeout_seconds)
        if payload.get("status") not in {"success", "complete"}:
            raise RuntimeError(f"OCR result is not complete (status={payload.get('status')!r}); refusing publication")
        findings = parse_ocr_output(payload)
        inline, fallback = validate_findings(findings, checkout, files)
        atomic_json(artifact / "validated-findings.json", {
            "inline": [f.model_dump() for f in inline], "summary_only": [f.model_dump() for f in fallback]})
        result = {"status": "reviewed_dry_run", "inline": len(inline), "summary_only": len(fallback)}
        if publish_enabled:
            state = ReviewState("1", "complete", candidate.head_sha, config_hash, profile.model,
                                profile.revision, profile.ocr_version, run_dir.name)
            result.update(publish(client, candidate.repository, candidate.number, candidate.head_sha,
                                  candidate.head_sha, inline, fallback, state, {"profile": profile.id}))
            result["status"] = "published"
        atomic_json(artifact / "publication.json", result)
        return result

