# Self Reviewer — Colab Open-Weight Pull Request Reviews

Self Reviewer is a manual, advisory pull-request review system built for the `SurveyBuilderLLM` organization. It runs the official BF16 `Qwen/Qwen3-Coder-30B-A3B-Instruct` model inside a Google Colab G4 runtime, drives Alibaba OpenCodeReview (`ocr`) through a loopback-only vLLM endpoint, validates every finding against the current diff, and can publish a neutral GitHub review plus one durable sticky summary.

It never executes code from a reviewed PR and has no hosted-inference fallback.

## How it works

One Colab run:

1. Loads `GITHUB_REVIEW_TOKEN` and optional `HF_TOKEN` from Colab Secrets.
2. Requires an RTX PRO 6000 Blackwell GPU, at least 90 GiB VRAM, 64 GiB system RAM, CUDA-visible PyTorch, and 100 GiB free disk.
3. Loads the pinned official BF16 Qwen checkpoint and exposes it only at `127.0.0.1:8000` through vLLM.
4. Runs a deterministic endpoint smoke test and `ocr llm test`.
5. Discovers open PRs from the repository allowlist and applies draft, branch, author, label, path, and size filters.
6. Checks the PR head against the state marker in the reviewer's previous sticky comment and previews discovery.
7. Clones each eligible PR into an isolated temporary directory and reviews `merge-base..head` sequentially.
8. Validates paths, changed lines, quoted source, duplicates, comment limits, and the live head SHA.
9. In publish mode, posts one neutral review and creates or updates the sticky summary.
10. Saves redacted artifacts and continues when an individual PR fails.

A completed review is identified by `(repository, PR number, head SHA, configuration hash, model revision, OCR version)`. The same tuple is skipped later. A new commit or changed configuration/model/OCR version makes it eligible again.

## Status and validation boundary

The control plane and local tests are implemented. The pinned vLLM/model/G4 combination still must be validated on a real Colab G4 before production publication. `PUBLISH` defaults to `False`; keep it off until the notebook smoke test and a seeded sandbox PR pass.

## Required runtime

| Setting | Required value |
|---|---|
| Runtime | Colab Python 3, latest runtime |
| Accelerator | G4 / RTX PRO 6000 Blackwell |
| High-RAM | On |
| Model | `Qwen/Qwen3-Coder-30B-A3B-Instruct` |
| Precision | Official BF16 checkpoint |
| Context | 32,768 tokens |
| vLLM concurrency | 1 |
| Tensor parallel | 1 |
| GPU memory utilization | 0.90 |

There is no A100, L4, T4, quantized, CPU-offload, smaller-model, or hosted-API fallback.

## GitHub token configuration

Create a fine-grained personal access token restricted to only the repositories in `config/repositories.yaml`. Grant:

- Metadata: read
- Contents: read
- Pull requests: read and write

Do not grant Actions, Administration, Deployments, Environments, Secrets, or Contents write. Add these to Colab Secrets:

- `GITHUB_REVIEW_TOKEN` — required
- `HF_TOKEN` — optional, only when Hugging Face requires authentication or higher limits

Tokens travel only in request headers or an ephemeral Git askpass helper. They are not stored in remotes, command arguments, notebooks, Drive caches, or artifacts.

## Colab deployment and first run

1. Open [`notebooks/aayvu_code_reviewer.ipynb`](notebooks/aayvu_code_reviewer.ipynb) in Colab.
2. Select **Python 3**, **G4 GPU**, **High-RAM On**, and the latest runtime.
3. Add the Colab Secrets above and enable notebook access.
4. Leave `RUN_MODE = "pending"` and `PUBLISH = False`.
5. Confirm `PROJECT_REF` is the immutable reviewer commit you intend to run. The checked-in notebook is already pinned; update it deliberately when upgrading. Never use a moving branch in production.
6. Run all cells. The notebook installs pins, checks hardware, starts vLLM, tests OCR, and previews discovery.
7. Inspect `runs/<run-id>/` for a deliberately seeded sandbox PR.
8. Set `PUBLISH = True` only for the sandbox, inspect the preview, and approve the interactive confirmation.
9. Rerun the unchanged PR and confirm it is `already_reviewed`.
10. Push another sandbox commit and confirm the new head becomes pending.

To target one PR:

```python
RUN_MODE = "explicit"
EXPLICIT_REPOSITORY = "SurveyBuilderLLM/backend"
EXPLICIT_PR = 42
PUBLISH = False
```

The notebook is only a launcher. Core logic lives in `src/aayvu_reviewer`, allowing a later move to a self-hosted GPU runner.

## Local installation and CLI

```bash
git clone https://github.com/sivab193/self-reviewer.git
cd self-reviewer
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
npm install -g @alibaba-group/open-code-review@1.13.0
pytest
```

Commands:

```bash
export GITHUB_REVIEW_TOKEN=...
aayvu-reviewer doctor
aayvu-reviewer discover
aayvu-reviewer discover --json
aayvu-reviewer review --pending --dry-run
aayvu-reviewer review --pending --publish
aayvu-reviewer review --repo SurveyBuilderLLM/backend --pr 42 --publish
aayvu-reviewer resume --run-id 20261014T220501Z
```

The model server must already be running for a local `review`. The Colab notebook handles hardware checks, server lifecycle, and endpoint testing.

## Repository configuration

`config/repositories.yaml` is the versioned allowlist. Production defaults to:

```yaml
trigger:
  mode: label
  labels_any: [ai-review]
```

Trigger modes:

- `label` requires a configured trigger label.
- `all_open` considers every otherwise eligible open PR.
- `explicit` considers only PR numbers supplied in the notebook or CLI.

Per-repository settings override defaults:

```yaml
repositories:
  - repository: SurveyBuilderLLM/backend
    rules: config/rules/backend.json
    base_branches: [main]
    excluded_head_branch_patterns: ['^dependabot/']
    excluded_labels: [no-ai-review]
    include_paths: ['src/**', 'tests/**']
    exclude_paths: ['**/generated/**']
```

Available controls include:

- `enabled`, `base_branches`, and `review_drafts`
- `head_branch_patterns` and `excluded_head_branch_patterns`
- `allowed_authors` and `excluded_authors`
- `labels_any`, `labels_all`, and `excluded_labels`
- `include_paths` and `exclude_paths`
- `limits.max_changed_files`, `max_changed_lines`, and `max_file_bytes`
- `ocr.effort`, `concurrency`, and `timeout_seconds`
- `publish.inline`, `sticky_summary`, and `advisory_only`

Repository names and regular expressions are validated before GitHub requests. Repositories outside the configured organization are rejected. Rules always resolve from this trusted project, not the PR checkout.

## Model configuration and cache

`config/model-profile.yaml` accepts only the fixed G4/BF16/32K profile. The model commit, vLLM version, and OCR version are pinned. Verify them with:

```bash
python scripts/verify_pins.py
```

The default cache is `/content/model-cache`. To use Google Drive, mount Drive and change only `cache_dir`; never put tokens or PR checkouts there. Runtime-local cache is normally faster.

## Trusted review rules

- `general.json` — correctness, security, privacy, reliability, compatibility
- `backend.json` — authorization, tenant boundaries, MongoDB, queues, packaging
- `worker.json` — idempotency, paid-call retries, terminal states, partial results
- `frontend.json` — auth state, API compatibility, data loss, accessibility, SSR
- `docs.json` — dangerous guidance, deployment claims, secrets, links, accessibility

## Publication behavior

Valid changed-line findings are sent in one Pull Request Review with event `COMMENT`. Findings without a safe inline location go into the sticky issue-comment summary. The reviewer never sends `APPROVE` or `REQUEST_CHANGES`.

Immediately before writing, it fetches the PR again and refuses publication if the head moved. Only a complete OCR result can receive a successful marker. Only markers authored by the authenticated reviewer identity are trusted later.

## Artifacts and recovery

```text
runs/<run-id>/
├── manifest.json
├── discovery.json
├── summary.json
└── prs/<owner>__<repo>__<number>/
    ├── metadata.json
    ├── ocr-result.json
    ├── ocr-stderr.log
    ├── validated-findings.json
    └── publication.json
```

Failed, timed-out, partial, malformed, and dry-run reviews remain eligible. If Colab disconnects, rerun discovery. If a write partially succeeds, inspect the PR and `publication.json` before retrying. The sticky summary is updated rather than duplicated.

## Security boundaries

- PR titles, descriptions, branches, filenames, source, and model output are untrusted.
- PR code, hooks, submodules, package managers, tests, notebooks, and executables are never run.
- Subprocesses use argument arrays with `shell=False`.
- Credentials never appear in Git remote URLs or process arguments.
- Absolute, traversal, missing, and checkout-escaping symlink paths are rejected.
- Inline lines must be changed right-side lines, and quoted source must match the reviewed head.
- Fake state markers from model output are neutralized.
- The live head is checked immediately before GitHub writes.
- Publication is advisory and cannot merge, approve, request changes, or modify source.

## Testing

```bash
pip install -e '.[test]'
pytest
python scripts/verify_pins.py
```

Unit tests cover configuration, filtering, marker state, diff/path validation, deduplication, redaction, and hardware gates. A real Colab G4 model load, 32K allocation, `ocr llm test`, one-file fixture, and seeded private-PR publication are still required before declaring the runtime profile production-ready.

## Troubleshooting

- **GPU rejected:** select G4 GPU and High-RAM, reconnect, and rerun.
- **Less than 100 GiB free:** start a fresh runtime or remove unrelated runtime files.
- **CUDA unavailable:** restart after selecting the GPU; do not switch to CPU inference.
- **vLLM exits:** inspect `runs/<run-id>/vllm.log` and record GPU, CUDA, PyTorch, vLLM, RAM, and VRAM details.
- **`ocr llm test` fails:** ensure vLLM is healthy and the endpoint is loopback.
- **No pending PRs:** check the `ai-review` label, base branch, filters, limits, and prior marker.
- **Summary-only finding:** its line was unchanged, its quotation mismatched, or the inline cap was reached.
- **GitHub 403:** verify repository selection and Pull requests read/write permission.

## Recommended rollout

1. Review an offline synthetic fixture without GitHub publication.
2. Use explicit mode on one private sandbox repository.
3. Inspect dry-run artifacts before enabling publication.
4. Pilot label-triggered reviews on backend and worker repositories.
5. Evaluate at least ten reviews for seeded-bug recall, false positives, line placement, latency, and GPU stability.
6. Add remaining repositories and move to a GitHub App with short-lived tokens if retained.

This is intentionally a manual, low-volume Colab system—not an always-on service, branch-protection check, or automatic approval mechanism.

## License

Apache-2.0. See `LICENSE` and `LICENSE-NOTICES.md`.
