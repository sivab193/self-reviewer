from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator


class CheckoutError(RuntimeError): pass


def _run(args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=300, check=False)
    if result.returncode:
        raise CheckoutError(f"command {args[:2]} failed: {result.stderr[:1000]}")
    return result.stdout.strip()


@contextmanager
def trusted_checkout(repository: str, base: str, head_sha: str, token: str) -> Iterator[tuple[Path, str]]:
    with tempfile.TemporaryDirectory(prefix="aayvu-review-") as directory:
        root = Path(directory)
        # Credentials are supplied only through an ephemeral askpass helper, never the remote URL.
        askpass = root / "askpass.sh"
        askpass.write_text('#!/bin/sh\ncase "$1" in *Username*) echo x-access-token;; *) printf "%s" "$AAYVU_GIT_TOKEN";; esac\n', encoding="utf-8")
        askpass.chmod(0o700)
        env = {**os.environ, "GIT_ASKPASS": str(askpass), "GIT_TERMINAL_PROMPT": "0", "AAYVU_GIT_TOKEN": token,
               "GIT_CONFIG_NOSYSTEM": "1"}
        repo_dir = root / "repo"
        _run(["git", "clone", "--no-checkout", "--filter=blob:none", f"https://github.com/{repository}.git", str(repo_dir)], env=env)
        _run(["git", "-c", "fetch.fsckObjects=true", "fetch", "--no-tags", "origin", base, head_sha], repo_dir, env)
        fetched = _run(["git", "rev-parse", f"{head_sha}^{{commit}}"], repo_dir, env)
        if fetched != head_sha:
            raise CheckoutError("fetched commit does not match API head SHA")
        _run(["git", "checkout", "--detach", head_sha], repo_dir, env)
        merge_base = _run(["git", "merge-base", f"origin/{base}", head_sha], repo_dir, env)
        askpass.unlink(missing_ok=True)
        yield repo_dir, merge_base

