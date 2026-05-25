import pytest
from tools.eps_v1_4.context_schema import has_existing_evidence

def test_flag_true_but_missing():
    ctx = {"evidence_paths": ["/nonexistent/path/VR-9999.json"]}
    assert has_existing_evidence(ctx) is False

def test_actual_files_exist(tmp_path):
    f = tmp_path / "VR-0001.json"
    f.write_text("{}")
    ctx = {"evidence_paths": [str(f)]}
    assert has_existing_evidence(ctx) is True

def test_partial_missing(tmp_path):
    f = tmp_path / "VR-0001.json"
    f.write_text("{}")
    ctx = {"evidence_paths": [str(f), "/nonexistent/VR-9999.json"]}
    assert has_existing_evidence(ctx) is False

def test_missing_evidence_paths():
    assert has_existing_evidence({}) is False
