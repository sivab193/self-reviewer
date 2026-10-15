from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .findings import Finding
from .github_client import GitHubClient
from .state import MARKER_NAME, ReviewState, parse_marker, render_marker


def finding_body(finding: Finding) -> str:
    return f"**{finding.severity.upper()} · {finding.category} — {finding.title}**\n\n{finding.body}"


def summary_body(state: ReviewState, inline: list[Finding], fallback: list[Finding], metadata: dict) -> str:
    counts = Counter(f.severity for f in inline + fallback)
    rows = "\n".join(f"- **{f.severity.upper()} — {f.title}** (`{f.path}:{f.line}`): {f.body}" for f in fallback)
    return f"""## Aayvu local-model review

Status: **complete**  
Head: `{state.head_sha}`  
Model: `{state.model}` @ `{state.model_revision[:12]}`  
OpenCodeReview: `{state.ocr_version}`  
Findings: {len(inline)} inline, {len(fallback)} summary-only ({dict(counts)})

### Findings without a valid inline position

{rows or "None."}

<details><summary>Runtime metadata</summary>

```json
{metadata}
```
</details>

{render_marker(state)}
"""


def publish(client: GitHubClient, repository: str, number: int, current_head: str, discovered_head: str,
            inline: list[Finding], fallback: list[Finding], state: ReviewState, metadata: dict) -> dict:
    # Re-read the PR immediately before any write; never post stale findings after a force-push.
    live_head = client.pull(repository, number)["head"]["sha"]
    if live_head != discovered_head or current_head != discovered_head:
        raise RuntimeError("PR head changed since discovery; refusing publication")
    review = None
    if inline:
        comments = [{"path": f.path, "line": f.line, "side": f.side, "body": finding_body(f)} for f in inline]
        review = client.create_review(repository, number, discovered_head, comments)
    body = summary_body(state, inline, fallback, metadata)
    login = client.current_login()
    existing = next((c for c in client.issue_comments(repository, number)
                     if c.get("user", {}).get("login") == login and parse_marker(c.get("body", ""))), None)
    summary = client.update_comment(repository, existing["id"], body) if existing else client.create_comment(repository, number, body)
    return {"review_id": review and review.get("id"), "summary_comment_id": summary.get("id"),
            "published_at": datetime.now(timezone.utc).isoformat()}

