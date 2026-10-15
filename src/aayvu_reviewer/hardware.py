from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil


class HardwareError(RuntimeError):
    pass


@dataclass(frozen=True)
class HardwareInfo:
    gpu_name: str
    gpu_vram_bytes: int
    system_ram_bytes: int
    free_disk_bytes: int
    cuda_visible: bool
    cuda_version: str | None
    torch_version: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def detect(cache_dir: Path = Path("/content/model-cache")) -> HardwareInfo:
    query = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if query.returncode != 0:
        raise HardwareError("nvidia-smi is unavailable: " + query.stderr.strip())
    first = query.stdout.strip().splitlines()[0].split(",")
    name, memory_mib = first[0].strip(), int(first[1].strip())
    try:
        import torch
        cuda_visible = bool(torch.cuda.is_available())
        cuda_version, torch_version = torch.version.cuda, torch.__version__
    except ImportError:
        cuda_visible, cuda_version, torch_version = False, None, None
    disk_root = cache_dir if cache_dir.exists() else Path("/content" if Path("/content").exists() else "/")
    return HardwareInfo(name, memory_mib * 1024**2, psutil.virtual_memory().total,
                        shutil.disk_usage(disk_root).free, cuda_visible, cuda_version, torch_version)


def validate(info: HardwareInfo) -> list[str]:
    errors: list[str] = []
    normalized = info.gpu_name.lower().replace("pro", "pro")
    if "rtx" not in normalized or "6000" not in normalized or "blackwell" not in normalized:
        errors.append(f"GPU is {info.gpu_name!r}; expected RTX PRO 6000 Blackwell")
    if info.gpu_vram_bytes < 90 * 1024**3:
        errors.append("GPU VRAM is below 90 GiB")
    if info.system_ram_bytes < 64 * 1024**3:
        errors.append("system RAM is below 64 GiB")
    if info.free_disk_bytes < 100 * 1024**3:
        errors.append("free disk is below 100 GiB")
    if not info.cuda_visible:
        errors.append("CUDA is not visible to PyTorch")
    return errors


def require_g4(info: HardwareInfo) -> None:
    errors = validate(info)
    if errors:
        raise HardwareError("; ".join(errors) + ". In Colab select Runtime > Change runtime type > G4 GPU, enable High-RAM, reconnect, and rerun.")


def write_hardware(info: HardwareInfo, path: Path) -> None:
    path.write_text(json.dumps(info.to_dict(), indent=2) + "\n", encoding="utf-8")

