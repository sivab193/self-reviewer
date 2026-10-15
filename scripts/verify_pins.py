from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
profile = yaml.safe_load((ROOT / "config/model-profile.yaml").read_text())
assert re.fullmatch(r"[0-9a-f]{40}", profile["revision"]), "model revision is not immutable"
with urllib.request.urlopen("https://registry.npmjs.org/@alibaba-group%2Fopen-code-review", timeout=20) as response:
    npm = json.load(response)
assert profile["ocr_version"] in npm["versions"], "pinned OCR release does not exist"
request = urllib.request.Request(
    f"https://huggingface.co/api/models/{profile['model']}/revision/{profile['revision']}",
    headers={"User-Agent": "aayvu-reviewer-pin-check"},
)
with urllib.request.urlopen(request, timeout=20) as response:
    model = json.load(response)
assert model["sha"] == profile["revision"], "model revision did not resolve exactly"
print("All external pins resolve exactly.")

