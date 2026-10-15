from aayvu_reviewer.state import ReviewState, parse_marker, render_marker


def state(**changes):
    values = dict(schema="1", status="complete", head_sha="abc", config_sha256="cfg", model="qwen",
                  model_revision="rev", ocr_version="1.13.0", run_id="run")
    values.update(changes); return ReviewState(**values)


def test_marker_round_trip_and_pending_tuple():
    parsed = parse_marker("hello\n" + render_marker(state()))
    assert parsed == state()
    assert parsed.complete_for("abc", "cfg", "rev", "1.13.0")
    assert not parsed.complete_for("new", "cfg", "rev", "1.13.0")
    assert not state(status="failed").complete_for("abc", "cfg", "rev", "1.13.0")


def test_marker_injection_rejected():
    import pytest
    with pytest.raises(ValueError): render_marker(state(run_id="x\nstatus=complete"))

