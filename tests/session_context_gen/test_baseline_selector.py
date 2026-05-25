import hashlib
import json
import pytest
from tools.session_context_gen.baseline_selector import select_baseline, BaselineSelectorError
from tools.session_context_gen.hash_utils import compute_hash


def _chain_hash(prev: str, payload_hash: str) -> str:
    return hashlib.sha256((prev + ":" + payload_hash).encode("utf-8")).hexdigest()


def _make_receipt(
    prev_chain_hash: str,
    artifact_path: str,
    artifact_hash: str,
    status: str = "PASS",
    rpu_id: str = "test-rpu-001",
    timestamp: str = "2026-04-21T00:00:00.000000Z",
) -> dict:
    payload = {"event_type": "SESSION_CONTEXT_GENERATED", "content": "test"}
    ph = compute_hash(payload)
    ch = _chain_hash(prev_chain_hash, ph)
    return {
        "status": status,
        "persistence_allowed": True,
        "candidate_rpu": {
            "schema_version": "ARSS-RPU-1.0",
            "rpu_id": rpu_id,
            "timestamp": timestamp,
            "actor_id": "test",
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


def test_T1_valid_chain_baseline_selected(tmp_path):
    """T1: valid chain — baseline selected normally."""
    artifact = tmp_path / "SESSION_CONTEXT.json"
    artifact.write_text('{"test": true}', encoding="utf-8")
    ah = compute_hash(artifact.read_text(encoding="utf-8"))

    genesis = "0" * 64
    r1 = _make_receipt(genesis, str(artifact), ah,
                       rpu_id="rpu-001", timestamp="2026-04-21T00:00:00.000000Z")
    r2_prev = r1["candidate_rpu"]["chain"]["chain_hash"]
    r2 = _make_receipt(r2_prev, str(artifact), ah,
                       rpu_id="rpu-002", timestamp="2026-04-21T01:00:00.000000Z")

    rdir = tmp_path / "receipts"
    rdir.mkdir()
    (rdir / "r1.json").write_text(json.dumps(r1), encoding="utf-8")
    (rdir / "r2.json").write_text(json.dumps(r2), encoding="utf-8")

    result = select_baseline(str(rdir))
    assert result["candidate_rpu"]["rpu_id"] == "rpu-002"


def test_T2_placeholder_receipt_fail_closed(tmp_path):
    """T2: placeholder receipt — FAIL-CLOSED."""
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{}', encoding="utf-8")

    r = _make_receipt("0" * 64, str(artifact), "")
    rdir = tmp_path / "receipts"
    rdir.mkdir()
    (rdir / "r.json").write_text(json.dumps(r), encoding="utf-8")

    with pytest.raises(BaselineSelectorError, match="Placeholder"):
        select_baseline(str(rdir))


def test_T3_artifact_missing_fail_closed(tmp_path):
    """T3: artifact missing — FAIL-CLOSED."""
    nonexistent = str(tmp_path / "missing_artifact.json")
    r = _make_receipt("0" * 64, nonexistent, "a" * 64)
    rdir = tmp_path / "receipts"
    rdir.mkdir()
    (rdir / "r.json").write_text(json.dumps(r), encoding="utf-8")

    with pytest.raises(BaselineSelectorError, match="Artifact not found"):
        select_baseline(str(rdir))


def test_T7_broken_chain_fail(tmp_path):
    """T7: broken chain — FAIL."""
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"data": 1}', encoding="utf-8")
    ah = compute_hash(artifact.read_text(encoding="utf-8"))

    genesis = "0" * 64
    r1 = _make_receipt(genesis, str(artifact), ah,
                       rpu_id="rpu-001", timestamp="2026-04-21T00:00:00.000000Z")
    wrong_prev = "deadbeef" * 8
    r2 = _make_receipt(wrong_prev, str(artifact), ah,
                       rpu_id="rpu-002", timestamp="2026-04-21T01:00:00.000000Z")

    rdir = tmp_path / "receipts"
    rdir.mkdir()
    (rdir / "r1.json").write_text(json.dumps(r1), encoding="utf-8")
    (rdir / "r2.json").write_text(json.dumps(r2), encoding="utf-8")

    with pytest.raises(BaselineSelectorError, match="Chain broken"):
        select_baseline(str(rdir))
