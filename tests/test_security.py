from aayvu_reviewer.hardware import HardwareInfo, validate
from aayvu_reviewer.redaction import redact


def test_redaction():
    assert "secret-value" not in redact("Authorization: Bearer secret-value", ("secret-value",))
    assert "github_pat_" not in redact("github_pat_abcdefghijklmnopqrstuvwxyz")


def test_hardware_gate():
    good = HardwareInfo("NVIDIA RTX PRO 6000 Blackwell Server Edition", 96 * 1024**3, 80 * 1024**3,
                        120 * 1024**3, True, "12.8", "2.7")
    assert validate(good) == []
    assert len(validate(HardwareInfo("T4", 16, 32, 50, False, None, None))) == 5
