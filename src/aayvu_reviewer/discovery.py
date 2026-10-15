from __future__ import annotations

import fnmatch
import re
from dataclasses import asdict, dataclass

from .config import ModelProfile, RepositoriesConfig, RepositoryOptions
from .github_client import GitHubClient
from .state import latest_state


@dataclass(frozen=True)
class PullCandidate:
    repository: str
    number: int
    title: str
    author: str
    base: str
    head_ref: str
    head_sha: str
    draft: bool
    changed_files: int
    changed_lines: int
    labels: tuple[str, ...]
    state: str
    reason: str
    rules: str

    def to_dict(self) -> dict:
        return asdict(self)


def _matches(value: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, value) for pattern in patterns)


def eligibility(pr: dict, options: RepositoryOptions, explicit_numbers: set[int] | None = None) -> tuple[str, str]:
    labels = {item["name"] for item in pr.get("labels", [])}
    author = pr.get("user", {}).get("login", "")
    head = pr.get("head", {}).get("ref", "")
    number = int(pr["number"])
    if not options.enabled: return "skipped", "repository disabled"
    if pr.get("state") != "open": return "skipped", "not open"
    if pr.get("draft") and not options.review_drafts: return "skipped", "draft"
    if pr.get("base", {}).get("ref") not in options.base_branches: return "skipped", "base branch"
    if options.head_branch_patterns and not _matches(head, options.head_branch_patterns): return "skipped", "head branch"
    if _matches(head, options.excluded_head_branch_patterns): return "skipped", "excluded head branch"
    if options.allowed_authors and author not in options.allowed_authors: return "skipped", "author"
    if author in options.excluded_authors: return "skipped", "excluded author"
    if labels & set(options.excluded_labels): return "skipped", "excluded label"
    if options.labels_any and not labels & set(options.labels_any): return "skipped", "labels_any"
    if options.labels_all and not set(options.labels_all) <= labels: return "skipped", "labels_all"
    if options.trigger.mode == "label" and not labels & set(options.trigger.labels_any): return "skipped", "trigger label"
    if options.trigger.mode == "explicit" and (not explicit_numbers or number not in explicit_numbers): return "skipped", "not explicit"
    if explicit_numbers is not None and number not in explicit_numbers: return "skipped", "not selected"
    files = int(pr.get("changed_files", 0)); lines = int(pr.get("additions", 0)) + int(pr.get("deletions", 0))
    if files > options.limits.max_changed_files: return "oversized", "changed files limit"
    if lines > options.limits.max_changed_lines: return "oversized", "changed lines limit"
    return "pending", "eligible"


def path_eligibility(files: list[dict], options: RepositoryOptions) -> tuple[str, str]:
    names = [str(item.get("filename", "")) for item in files]
    included = [name for name in names if not options.include_paths or any(fnmatch.fnmatch(name, p) for p in options.include_paths)]
    reviewable = [name for name in included if not any(fnmatch.fnmatch(name, p) for p in options.exclude_paths)]
    if not reviewable:
        return "skipped", "no paths matched"
    return "pending", "eligible"


def discover(client: GitHubClient, config: RepositoriesConfig, profile: ModelProfile, config_hash: str,
             explicit: dict[str, set[int]] | None = None, accept_previous_config: bool = False) -> list[PullCandidate]:
    results: list[PullCandidate] = []
    for repo in config.repositories:
        options = config.resolved(repo)
        if not options.enabled:
            continue
        pulls: dict[int, dict] = {}
        if explicit and repo.repository in explicit:
            for number in explicit[repo.repository]: pulls[number] = client.pull(repo.repository, number)
        else:
            for base in options.base_branches:
                for pr in client.open_pulls(repo.repository, base): pulls[int(pr["number"])] = pr
        for listed_pr in pulls.values():
            # The list endpoint omits reliable size totals; always hydrate the individual PR.
            pr = client.pull(repo.repository, int(listed_pr["number"]))
            state, reason = eligibility(pr, options, explicit.get(repo.repository) if explicit else None)
            if state == "pending":
                files = client.pull_files(repo.repository, int(pr["number"]))
                state, reason = path_eligibility(files, options)
            if state == "pending":
                prior = latest_state(client.issue_comments(repo.repository, int(pr["number"])), client.current_login())
                if prior and prior.complete_for(pr["head"]["sha"], config_hash, profile.revision, profile.ocr_version, accept_previous_config):
                    state, reason = "already_reviewed", "matching complete marker"
            results.append(PullCandidate(repo.repository, int(pr["number"]), pr.get("title", ""),
                pr.get("user", {}).get("login", ""), pr["base"]["ref"], pr["head"]["ref"], pr["head"]["sha"],
                bool(pr.get("draft")), int(pr.get("changed_files", 0)), int(pr.get("additions", 0)) + int(pr.get("deletions", 0)),
                tuple(label["name"] for label in pr.get("labels", [])), state, reason, repo.rules))
    return results
