from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .config import configuration_hash, load_model_profile, load_repositories
from .discovery import PullCandidate, discover as discover_pulls
from .github_client import GitHubClient
from .hardware import HardwareError, detect, require_g4
from .reporting import atomic_json

app = typer.Typer(no_args_is_help=True)
console = Console()
ROOT = Path(__file__).resolve().parents[2]


def paths(config: Path | None, profile: Path | None) -> tuple[Path, Path]:
    return config or ROOT / "config/repositories.yaml", profile or ROOT / "config/model-profile.yaml"


def configs(config: Path | None, profile: Path | None):
    cp, mp = paths(config, profile)
    repos, model = load_repositories(cp), load_model_profile(mp)
    return repos, model, configuration_hash(repos, model, ROOT)


def token() -> str:
    value = os.environ.get("GITHUB_REVIEW_TOKEN")
    if not value: raise typer.BadParameter("GITHUB_REVIEW_TOKEN is required (load it from Colab Secrets)")
    return value


def show(items: list[PullCandidate]) -> None:
    table = Table("Repository", "PR", "Base", "Head", "Files", "Lines", "State", "Reason")
    for p in items: table.add_row(p.repository, str(p.number), p.base, p.head_sha[:8], str(p.changed_files), str(p.changed_lines), p.state, p.reason)
    console.print(table)


@app.command()
def doctor(config: Path | None = None, profile: Path | None = None) -> None:
    repos, model, fingerprint = configs(config, profile)
    console.print(f"Configuration valid ({len(repos.repositories)} repositories, sha256 {fingerprint[:12]})")
    info = detect(Path(model.cache_dir))
    require_g4(info)
    ocr = subprocess.run(["ocr", "version"], capture_output=True, text=True, check=False)
    if ocr.returncode: raise typer.Exit("OCR executable missing or broken")
    if model.ocr_version not in ocr.stdout: raise typer.Exit(f"Expected OCR {model.ocr_version}; got {ocr.stdout.strip()}")
    console.print(f"Hardware ready: {info.gpu_name}")


@app.command("discover")
def discover_command(as_json: Annotated[bool, typer.Option("--json")] = False,
                     config: Path | None = None, profile: Path | None = None) -> None:
    repos, model, fingerprint = configs(config, profile)
    client = GitHubClient(token)
    try: items = discover_pulls(client, repos, model, fingerprint)
    finally: client.close()
    if as_json: console.print_json(json.dumps([x.to_dict() for x in items]))
    else: show(items)


@app.command()
def review(pending: Annotated[bool, typer.Option("--pending")] = False,
           dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
           publish: Annotated[bool, typer.Option("--publish")] = False,
           repo: str | None = None, pr: int | None = None,
           config: Path | None = None, profile: Path | None = None,
           run_root: Path = Path("runs")) -> None:
    if publish == dry_run: raise typer.BadParameter("choose exactly one of --dry-run or --publish")
    if not pending and not (repo and pr): raise typer.BadParameter("use --pending or both --repo and --pr")
    repos, model, fingerprint = configs(config, profile)
    client = GitHubClient(token); explicit = {repo: {pr}} if repo and pr else None
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = run_root / run_id; run_dir.mkdir(parents=True, exist_ok=False)
    try:
        items = discover_pulls(client, repos, model, fingerprint, explicit)
        atomic_json(run_dir / "discovery.json", [x.to_dict() for x in items]); show(items)
        eligible = [x for x in items if x.state == "pending"]
        if publish and not typer.confirm(f"Publish advisory reviews for {len(eligible)} PR(s)?", default=False):
            raise typer.Abort()
        from .reviewer import review_candidate
        results = []
        for item in eligible:
            try: results.append({"repository": item.repository, "pr": item.number, **review_candidate(item, client, token(), repos, model, fingerprint, ROOT, run_dir, publish)})
            except Exception as exc: results.append({"repository": item.repository, "pr": item.number, "status": "failed", "error": str(exc)})
        atomic_json(run_dir / "summary.json", results)
        atomic_json(run_dir / "manifest.json", {"run_id": run_id, "config_sha256": fingerprint,
                    "model_revision": model.revision, "ocr_version": model.ocr_version, "publish": publish})
        console.print(f"Artifacts: {run_dir.resolve()}")
    finally: client.close()


@app.command()
def resume(run_id: str, run_root: Path = Path("runs")) -> None:
    manifest = run_root / run_id / "manifest.json"
    if not manifest.exists(): raise typer.BadParameter("run not found")
    console.print_json(manifest.read_text(encoding="utf-8"))
    console.print("Resume validates artifacts but publication must be re-run explicitly to prevent stale writes.")


if __name__ == "__main__": app()
