from aayvu_reviewer.config import RepositoryOptions, Trigger
from aayvu_reviewer.discovery import eligibility


def pr(**changes):
    value = {"number": 7, "state": "open", "draft": False, "base": {"ref": "main"}, "head": {"ref": "feature"},
             "user": {"login": "dev"}, "labels": [{"name": "ai-review"}], "changed_files": 2, "additions": 5, "deletions": 2}
    value.update(changes); return value


def test_label_trigger_and_limits():
    options = RepositoryOptions(trigger=Trigger(mode="label", labels_any=["ai-review"]))
    assert eligibility(pr(), options) == ("pending", "eligible")
    assert eligibility(pr(labels=[]), options)[0] == "skipped"
    assert eligibility(pr(changed_files=100), options)[0] == "oversized"


def test_draft_and_explicit():
    assert eligibility(pr(draft=True), RepositoryOptions())[1] == "draft"
    options = RepositoryOptions(trigger=Trigger(mode="explicit"))
    assert eligibility(pr(), options, {7})[0] == "pending"
    assert eligibility(pr(), options, {9})[0] == "skipped"

