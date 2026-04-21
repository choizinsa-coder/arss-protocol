import hashlib
import json
import os
import pytest
from tools.session_context_gen.generation_pipeline import run_pipeline, PipelineError
from tools.session_context_gen.hash_utils import compute_hash


def _chain_hash(prev: str, payload_hash: str) -> str:
    return hashlib.sha256((prev + ":" + payload_hash).encode("utf-8")).hexdigest()


def _make_receipt_file(path, artifact_path, artifact_hash, prev_chain_hash="0" * 64):
    payload = {"event_type": "SESSION_CONTEXT_GENERATED", "content": "test"}
    ph = compute_hash(payload)
    ch = _chain_hash(prev_chain_hash, ph)
    receipt = {
        "status": "PASS",
        "persistence_allowed": True,
        "candidate_rpu": {
            "schema_version": "ARSS-RPU-1.0",
            "rpu_id": "rpu-bootstrap",
            "timestamp": "2026-04-20T00:00:00.000000Z",
            "actor_id": "bootstrap",
            "payload": payload,
            "chain": {
                "payload_hash": ph,
                "prev_chain_hash": prev_chain_hash,
                "chain_hash": ch,
            },
            "governance_context": {
                "policy_id": "ARSS_HUB_PROTOCOL_v1.2",
                "authority_root": "Beo",
                "jurisdiction": "AIBA_GLOBAL",
            },
        },
        "extension": {
            "artifact_path": artifact_path,
            "artifact_hash": artifact_hash,
            "extension_version": "1.0",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)


def test_pipeline_success(tmp_path):
    input_data = {"version": "3.1", "state_events": [{"event_id": "e1", "event_type": "TEST"}]}
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(input_data), encoding="utf-8")
    input_hash = compute_hash(input_file.read_text(encoding="utf-8"))

    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    _make_receipt_file(str(receipts_dir / "boot.json"), str(input_file), input_hash)

    output_dir = tmp_path / "staging"
    result = run_pipeline(str(input_file), str(receipts_dir), str(output_dir))

    assert result.status == "SUCCESS"
    assert result.output_path is not None
    assert os.path.exists(result.output_path)
    assert result.receipt_path is not None
    assert os.path.exists(result.receipt_path)

    receipt = json.loads(open(result.receipt_path, encoding="utf-8").read())
    assert receipt["status"] == "PASS"
    assert receipt["candidate_rpu"]["schema_version"] == "ARSS-RPU-1.0"
    assert "extension" in receipt
    assert receipt["extension"]["artifact_hash"]


def test_pipeline_fail_artifact_not_found(tmp_path):
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    with pytest.raises(PipelineError, match="artifact not found"):
        run_pipeline(str(tmp_path / "missing.json"), str(receipts_dir), str(tmp_path / "out"))


def test_pipeline_fail_no_baseline(tmp_path):
    input_file = tmp_path / "input.json"
    input_file.write_text('{"test": true}', encoding="utf-8")
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    with pytest.raises(PipelineError, match="baseline not found"):
        run_pipeline(str(input_file), str(receipts_dir), str(tmp_path / "out"))
