from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Trigger(StrictModel):
    mode: Literal["all_open", "label", "explicit"] = "label"
    labels_any: list[str] = Field(default_factory=list)


class Limits(StrictModel):
    max_changed_files: int = Field(75, gt=0)
    max_changed_lines: int = Field(8000, gt=0)
    max_file_bytes: int = Field(500_000, gt=0)


class Publish(StrictModel):
    inline: bool = True
    sticky_summary: bool = True
    advisory_only: bool = True


class OCR(StrictModel):
    effort: Literal["low", "medium", "high"] = "medium"
    concurrency: Literal[1] = 1
    timeout_seconds: int = Field(3600, ge=60, le=14400)


class RepositoryOptions(StrictModel):
    enabled: bool = True
    base_branches: list[str] = Field(default_factory=lambda: ["main"])
    review_drafts: bool = False
    trigger: Trigger = Field(default_factory=Trigger)
    limits: Limits = Field(default_factory=Limits)
    publish: Publish = Field(default_factory=Publish)
    ocr: OCR = Field(default_factory=OCR)
    head_branch_patterns: list[str] = Field(default_factory=list)
    excluded_head_branch_patterns: list[str] = Field(default_factory=list)
    allowed_authors: list[str] = Field(default_factory=list)
    excluded_authors: list[str] = Field(default_factory=list)
    labels_any: list[str] = Field(default_factory=list)
    labels_all: list[str] = Field(default_factory=list)
    excluded_labels: list[str] = Field(default_factory=list)
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)

    @field_validator("head_branch_patterns", "excluded_head_branch_patterns")
    @classmethod
    def valid_patterns(cls, values: list[str]) -> list[str]:
        for value in values:
            re.compile(value)
        return values


class RepositoryOverride(StrictModel):
    repository: str
    rules: str
    enabled: bool | None = None
    base_branches: list[str] | None = None
    review_drafts: bool | None = None
    trigger: Trigger | None = None
    limits: Limits | None = None
    publish: Publish | None = None
    ocr: OCR | None = None
    head_branch_patterns: list[str] | None = None
    excluded_head_branch_patterns: list[str] | None = None
    allowed_authors: list[str] | None = None
    excluded_authors: list[str] | None = None
    labels_any: list[str] | None = None
    labels_all: list[str] | None = None
    excluded_labels: list[str] | None = None
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None

    @field_validator("repository")
    @classmethod
    def valid_repository(cls, value: str) -> str:
        if not REPOSITORY_RE.fullmatch(value):
            raise ValueError("repository must be owner/name")
        return value

    @field_validator("head_branch_patterns", "excluded_head_branch_patterns")
    @classmethod
    def valid_optional_patterns(cls, values: list[str] | None) -> list[str] | None:
        for value in values or []:
            re.compile(value)
        return values


class RepositoriesConfig(StrictModel):
    version: Literal[1]
    organization: str
    defaults: RepositoryOptions
    repositories: list[RepositoryOverride]

    @model_validator(mode="after")
    def validate_allowlist(self) -> "RepositoriesConfig":
        names = [r.repository for r in self.repositories]
        if len(names) != len(set(names)):
            raise ValueError("duplicate repository in allowlist")
        if any(not name.startswith(self.organization + "/") for name in names):
            raise ValueError("repository is outside configured organization")
        return self

    def resolved(self, item: RepositoryOverride) -> RepositoryOptions:
        data = self.defaults.model_dump()
        for key, value in item.model_dump(exclude={"repository", "rules"}).items():
            if value is not None:
                data[key] = value
        return RepositoryOptions.model_validate(data)


class ModelProfile(StrictModel):
    id: Literal["colab-g4-bf16"]
    model: Literal["Qwen/Qwen3-Coder-30B-A3B-Instruct"]
    revision: str
    dtype: Literal["bfloat16"]
    served_model_name: str
    host: Literal["127.0.0.1"]
    port: int = Field(8000, ge=1024, le=65535)
    max_model_len: Literal[32768]
    gpu_memory_utilization: float = Field(0.9, ge=0.8, le=0.95)
    tensor_parallel_size: Literal[1]
    request_concurrency: Literal[1]
    cache_dir: str
    vllm_version: str
    ocr_version: str

    @field_validator("revision")
    @classmethod
    def immutable_revision(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("model revision must be an immutable 40-character commit SHA")
        return value


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def load_repositories(path: Path) -> RepositoriesConfig:
    return RepositoriesConfig.model_validate(load_yaml(path))


def load_model_profile(path: Path) -> ModelProfile:
    return ModelProfile.model_validate(load_yaml(path))


def configuration_hash(config: RepositoriesConfig, profile: ModelProfile, root: Path) -> str:
    payload = {"repositories": config.model_dump(), "profile": profile.model_dump(), "rules": {}}
    for repo in config.repositories:
        rule_path = (root / repo.rules).resolve()
        if not rule_path.is_relative_to(root.resolve()):
            raise ValueError("rule path escapes trusted project root")
        payload["rules"][repo.rules] = json.loads(rule_path.read_text(encoding="utf-8"))
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()

