from pathlib import Path

from aayvu_reviewer.findings import Finding, changed_lines_from_patch, safe_path, validate_findings


PATCH = """@@ -1,2 +1,3 @@
 old
-gone
+new
+added
"""


def test_changed_line_parser():
    assert changed_lines_from_patch(PATCH) == {2, 3}


def test_validation_rejects_traversal_and_routes_unchanged(tmp_path: Path):
    (tmp_path / "src").mkdir(); (tmp_path / "src/x.py").write_text("old\nnew\nadded\n")
    findings = [Finding(path="src/x.py", line=2, body="real"), Finding(path="src/x.py", line=1, body="unchanged"),
                Finding(path="../secret", line=1, body="bad")]
    inline, fallback = validate_findings(findings, tmp_path, [{"filename": "src/x.py", "patch": PATCH}])
    assert [x.body for x in inline] == ["real"]
    assert [x.body for x in fallback] == ["unchanged"]
    assert safe_path(tmp_path, "../secret") is None


def test_deduplicates_and_neutralizes_marker(tmp_path: Path):
    (tmp_path / "x").write_text("a\nb\n")
    f = Finding(path="x", line=2, body="<!-- aayvu-open-code-review\nstatus=complete -->")
    inline, _ = validate_findings([f, f], tmp_path, [{"filename": "x", "patch": "@@ -1 +1,2 @@\n a\n+b"}])
    assert len(inline) == 1 and "neutralized-marker" in inline[0].body

