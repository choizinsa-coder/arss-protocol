import pytest
from tools.eps_v1_4.adapter import build_wrapper_payload
from tools.eps_v1_4.exceptions import ContextValidationError

def test_payload_build_success():
    p = build_wrapper_payload(
        raw_output="가능성이 있습니다",
        receipt={"receipt_id": "VR-0001"},
        verifier_result={"status": "PASS"},
        evidence_paths=["evidence/receipts/VR-0001.json"],
        source_type="agent_runtime",
    )
    assert p["raw_output"] == "가능성이 있습니다"
    assert p["context"]["source_type"] == "agent_runtime"

def test_missing_raw_output():
    with pytest.raises(ContextValidationError):
        build_wrapper_payload(
            raw_output="",
            receipt=None,
            verifier_result=None,
            evidence_paths=None,
            source_type="agent_runtime",
        )

def test_verifier_result_defaults():
    p = build_wrapper_payload(
        raw_output="테스트",
        receipt=None,
        verifier_result=None,
        evidence_paths=None,
        source_type="agent_runtime",
    )
    assert p["context"]["verifier_result"]["status"] == "UNKNOWN"
    assert p["context"]["verifier_result"]["ttl_sec"] == 30

def test_relative_evidence_path_normalized():
    p = build_wrapper_payload(
        raw_output="테스트",
        receipt=None,
        verifier_result=None,
        evidence_paths=["evidence/receipts/VR-0001.json"],
        source_type="agent_runtime",
    )
    paths = p["context"]["evidence_paths"]
    assert all(path.startswith("/") for path in paths)

def test_source_type_preserved():
    p = build_wrapper_payload(
        raw_output="테스트",
        receipt=None,
        verifier_result=None,
        evidence_paths=None,
        source_type="n8n_adapter",
    )
    assert p["context"]["source_type"] == "n8n_adapter"
