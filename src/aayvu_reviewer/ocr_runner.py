from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

from .redaction import redact


class OCRError(RuntimeError): pass


def run_ocr(checkout: Path, merge_base: str, head_sha: str, rule_file: Path, output: Path,
            endpoint: str, model: str, timeout: int, token: str = "local-colab-only") -> dict:
    args = ["ocr", "review", "--repo", str(checkout), "--from", merge_base, "--to", head_sha,
            "--format", "json", "--audience", "agent", "--concurrency", "1", "--rule", str(rule_file)]
    env = {**os.environ, "OCR_LLM_URL": endpoint, "OCR_LLM_AUTH_TOKEN": token,
           "OCR_LLM_MODEL": model, "OCR_LLM_PROTOCOL": "openai"}
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        raise OCRError(f"OCR timed out after {timeout}s")
    (output.parent / "ocr-stderr.log").write_text(redact(stderr, (token,)), encoding="utf-8")
    if process.returncode:
        raise OCRError(f"OCR exited {process.returncode}: {redact(stderr, (token,))[-1000:]}")
    output.write_text(stdout, encoding="utf-8")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise OCRError("OCR did not emit valid JSON") from exc

