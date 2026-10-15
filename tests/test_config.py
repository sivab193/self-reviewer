from pathlib import Path

import pytest

from aayvu_reviewer.config import configuration_hash, load_model_profile, load_repositories

ROOT = Path(__file__).parents[1]


def test_config_loads_and_hash_is_stable():
    repos = load_repositories(ROOT / "config/repositories.yaml")
    profile = load_model_profile(ROOT / "config/model-profile.yaml")
    assert len(repos.repositories) == 8
    assert configuration_hash(repos, profile, ROOT) == configuration_hash(repos, profile, ROOT)


def test_outside_org_rejected(tmp_path):
    value = (ROOT / "config/repositories.yaml").read_text().replace("SurveyBuilderLLM/backend", "evil/backend")
    path = tmp_path / "repos.yaml"; path.write_text(value)
    with pytest.raises(ValueError): load_repositories(path)

