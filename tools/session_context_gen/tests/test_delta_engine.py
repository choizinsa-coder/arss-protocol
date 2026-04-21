import pytest
from tools.session_context_gen.delta_engine import compute_delta, DeltaResult, DeltaEngineError
from tools.session_context_gen.hash_utils import compute_hash


def _make_baseline_receipt(artifact_hash: str) -> dict:
    from tools.session_context_gen.hash_utils import compute_hash as ch
    import hashlib
    payload = {"event_type": "SESSION_CONTEXT_GENERATED", "content": "test"}
    ph = ch(payload)
    chain_h = hashlib.sha256(("0" * 64 + ":" + ph).encode("utf-8")).hexdigest()
    return {
        "status": "PASS",
        "persistence_allowed": True,
        "candidate_rpu": {
            "schema_version": "ARSS-RPU-1.0",
            "rpu_id": "test-001",
            "timestamp": "2026-04-21T00:00:00.000000Z",
            "actor_id": "test",
            "payload": payload,
            "chain": {
                "payload_hash": ph,
                "prev_chain_hash": "0" * 64,
                "chain_hash": chain_h,
            },
            "governance_context": {
                "policy_id": "ARSS_HUB_PROTOCOL_v1.2",
                "authority_root": "Beo",
                "jurisdiction": "AIBA_GLOBAL",
            },
        },
        "extension": {
            "artifact_path": "/tmp/test.json",
            "artifact_hash": artifact_hash,
            "extension_version": "1.0",
        },
    }


def test_T4_artifact_hash_identical_no_change(tmp_path):
    """T4: artifact_hash identical — NO_CHANGE."""
    content = '{"session": 1}'
    artifact = tmp_path / "ctx.json"
    artifact.write_text(content, encoding="utf-8")
    h = compute_hash(content)

    baseline = _make_baseline_receipt(h)
    result = compute_delta(baseline, str(artifact))

    assert result.status == "NO_CHANGE"
    assert result.current_hash == result.baseline_hash


def test_T5_artifact_hash_different_changed(tmp_path):
    """T5: artifact_hash different — CHANGED."""
    artifact = tmp_path / "ctx.json"
    artifact.write_text('{"session": 2}', encoding="utf-8")

    baseline = _make_baseline_receipt("a" * 64)
    result = compute_delta(baseline, str(artifact))

    assert result.status == "CHANGED"
    assert result.current_hash != result.baseline_hash


def test_line_count_diagnostic_only(tmp_path):
    """line_count in diagnostic only — not used for judgment."""
    content = "line1\nline2\n"
    artifact = tmp_path / "ctx.json"
    artifact.write_text(content, encoding="utf-8")
    h = compute_hash(content)

    baseline = _make_baseline_receipt(h)
    result = compute_delta(baseline, str(artifact))

    assert result.status == "NO_CHANGE"
    assert "line_count" in result.diagnostic
    assert isinstance(result.diagnostic["line_count"], int)


def test_missing_artifact_raises(tmp_path):
    baseline = _make_baseline_receipt("a" * 64)
    with pytest.raises(DeltaEngineError, match="Artifact not found"):
        compute_delta(baseline, str(tmp_path / "nonexistent.json"))


def test_missing_baseline_hash_raises(tmp_path):
    artifact = tmp_path / "ctx.json"
    artifact.write_text("{}", encoding="utf-8")
    baseline = _make_baseline_receipt("")
    with pytest.raises(DeltaEngineError, match="missing extension.artifact_hash"):
        compute_delta(baseline, str(artifact))
