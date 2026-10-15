from __future__ import annotations

import atexit
import os
import subprocess
import time
from pathlib import Path

import httpx

from .config import ModelProfile


class ModelServerError(RuntimeError): pass


class ModelServer:
    def __init__(self, profile: ModelProfile, log_path: Path, hf_token: str | None = None):
        self.profile, self.log_path, self.hf_token = profile, log_path, hf_token
        self.process: subprocess.Popen | None = None

    @property
    def base_url(self) -> str: return f"http://{self.profile.host}:{self.profile.port}/v1"

    def start(self, timeout: int = 1800) -> None:
        if self.profile.host != "127.0.0.1": raise ModelServerError("model server must be loopback-only")
        args = ["python", "-m", "vllm.entrypoints.openai.api_server", "--host", self.profile.host,
                "--port", str(self.profile.port), "--model", self.profile.model, "--revision", self.profile.revision,
                "--served-model-name", self.profile.served_model_name, "--dtype", self.profile.dtype,
                "--max-model-len", str(self.profile.max_model_len), "--gpu-memory-utilization", str(self.profile.gpu_memory_utilization),
                "--tensor-parallel-size", "1", "--download-dir", self.profile.cache_dir, "--api-key", "local-colab-only"]
        env = {**os.environ};
        if self.hf_token: env["HF_TOKEN"] = self.hf_token
        log = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        atexit.register(self.stop)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None: raise ModelServerError(f"vLLM exited early; see {self.log_path}")
            try:
                if httpx.get(self.base_url + "/models", headers={"Authorization": "Bearer local-colab-only"}, timeout=5).is_success:
                    self.smoke_test(); return
            except httpx.HTTPError: pass
            time.sleep(5)
        self.stop(); raise ModelServerError("vLLM did not become healthy before timeout")

    def smoke_test(self) -> None:
        body = {"model": self.profile.served_model_name, "temperature": 0, "max_tokens": 8,
                "messages": [{"role": "user", "content": "Reply with exactly READY"}]}
        response = httpx.post(self.base_url + "/chat/completions", json=body,
                              headers={"Authorization": "Bearer local-colab-only"}, timeout=120)
        response.raise_for_status()
        if "READY" not in response.json()["choices"][0]["message"]["content"]:
            raise ModelServerError("deterministic model smoke test failed")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid, 15)
            try: self.process.wait(30)
            except subprocess.TimeoutExpired: os.killpg(self.process.pid, 9)
