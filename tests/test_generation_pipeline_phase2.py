import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.session_context_gen.generation_pipeline import (
    run_pipeline,
    PipelineResult,
    PipelineError,
)
from tools.session_context_gen.hash_utils import compute_hash


def _make_receipt(chain_hash="aaaa1234", artifact_hash="bbbb5678"):
    return {
        "status": "PASS",
        "persistence_allowed": True,
        "candidate_rpu": {
            "schema_version": "ARSS-RPU-1.0",
            "rpu_id": "test-rpu-id",
            "timestamp": "2026-05-05T00:00:00.000000Z",
            "actor_id": "test",
            "payload": {"event_type": "TEST", "content": "test"},
            "chain": {
                "payload_hash": "ph",
                "prev_chain_hash": "prev",
                "chain_hash": chain_hash,
            },
            "governance_context": {},
        },
        "extension": {
            "artifact_path": "/tmp/test.json",
            "artifact_hash": artifact_hash,
            "prev_artifact_hash": "",
            "extension_version": "1.0",
        },
    }


def _make_minimal_full_context():
    return {
        "session_count": 88,
        "schema_version": "4.0",
        "chain": {"tip": "eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd"},
        "state_events": [],
        "active_tasks": [],
        "lessons": [],
        "pending_tasks": [],
        "canonical_rules": {},
        "decisions": [],
    }


def _make_minimal_runtime_context():
    """FULL fixture와 정합되는 임시 RUNTIME fixture."""
    return {
        "_zone": "SESSION_STATE_RUNTIME",
        "_source_session": 88,
        "session_count": 88,
        "schema_version": "4.0",
        "generated_at": "2026-05-06T00:00:00.000+09:00",
        "chain": {
            "tip": "eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd"
        },
        "agent_focus": {},
        "active_tasks": [],
        "sync_meta": {},
        "session_delta": [],
    }


def _setup_dirs(tmp):
    receipts_dir = os.path.join(tmp, "receipts")
    output_dir = os.path.join(tmp, "output")
    os.makedirs(receipts_dir)
    os.makedirs(output_dir)
    return receipts_dir, output_dir


def _write_receipt(receipts_dir, receipt):
    rpu_id = receipt["candidate_rpu"]["rpu_id"]
    path = os.path.join(receipts_dir, f"receipt_{rpu_id}.json")
    with open(path, "w") as f:
        json.dump(receipt, f)
    return path


def _write_input(tmp, data):
    path = os.path.join(tmp, "SESSION_CONTEXT_FULL.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _write_runtime(tmp, data):
    path = os.path.join(tmp, "SESSION_STATE_RUNTIME.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def test_tc1_pipeline_success_runtime_first():
    tmp = tempfile.mkdtemp()
    try:
        receipts_dir, output_dir = _setup_dirs(tmp)
        _write_receipt(receipts_dir, _make_receipt())
        input_path = _write_input(tmp, _make_minimal_full_context())
        runtime_path = _write_runtime(tmp, _make_minimal_runtime_context())
        result = run_pipeline(input_path, receipts_dir, output_dir, runtime_path=runtime_path)
        assert result.status == "SUCCESS", f"TC-1 FAIL: status={result.status}"
        assert result.runtime_path is not None
        assert result.boot_path is not None
        assert result.runtime_hash is not None
        assert result.boot_hash is not None
        assert result.runtime_pair_hash is not None
        assert os.path.exists(result.runtime_path), "RUNTIME file missing"
        assert os.path.exists(result.boot_path), "BOOT file missing"
        with open(result.output_path, "r") as f:
            out = json.load(f)
        assert out["_pipeline_meta"]["runtime_first"] is True
        assert out["_pipeline_meta"]["pipeline_version"] == "session_context_gen/2.0"
    finally:
        shutil.rmtree(tmp)


def test_tc2_runtime_pair_hash_integrity():
    tmp = tempfile.mkdtemp()
    try:
        receipts_dir, output_dir = _setup_dirs(tmp)
        _write_receipt(receipts_dir, _make_receipt())
        input_path = _write_input(tmp, _make_minimal_full_context())
        runtime_path = _write_runtime(tmp, _make_minimal_runtime_context())
        result = run_pipeline(input_path, receipts_dir, output_dir, runtime_path=runtime_path)
        with open(result.boot_path, "r") as f:
            boot_data = json.load(f)
        with open(result.runtime_path, "r") as f:
            runtime_data = json.load(f)
        expected_runtime_hash = compute_hash(runtime_data)
        actual_pair_hash = boot_data.get("boot_meta", {}).get("runtime_pair_hash")
        assert actual_pair_hash == expected_runtime_hash, (
            f"TC-2 FAIL: runtime_pair_hash mismatch "
            f"expected={expected_runtime_hash} actual={actual_pair_hash}"
        )
    finally:
        shutil.rmtree(tmp)


def test_tc3_pair_validator_pass():
    tmp = tempfile.mkdtemp()
    try:
        receipts_dir, output_dir = _setup_dirs(tmp)
        _write_receipt(receipts_dir, _make_receipt())
        input_path = _write_input(tmp, _make_minimal_full_context())
        runtime_path = _write_runtime(tmp, _make_minimal_runtime_context())
        result = run_pipeline(input_path, receipts_dir, output_dir, runtime_path=runtime_path)
        pv = result.validator_results.get("pair_validator", {})
        assert pv.get("pass") is True, f"TC-3 FAIL: pair_validator={pv}"
    finally:
        shutil.rmtree(tmp)


def test_tc4_boundary_validator_pass():
    tmp = tempfile.mkdtemp()
    try:
        receipts_dir, output_dir = _setup_dirs(tmp)
        _write_receipt(receipts_dir, _make_receipt())
        input_path = _write_input(tmp, _make_minimal_full_context())
        runtime_path = _write_runtime(tmp, _make_minimal_runtime_context())
        result = run_pipeline(input_path, receipts_dir, output_dir, runtime_path=runtime_path)
        bv = result.validator_results.get("boundary_enforcement_validator", {})
        assert bv.get("pass") is True, f"TC-4 FAIL: boundary_validator={bv}"
    finally:
        shutil.rmtree(tmp)


def test_tc5_receipt_contains_pair_info():
    tmp = tempfile.mkdtemp()
    try:
        receipts_dir, output_dir = _setup_dirs(tmp)
        _write_receipt(receipts_dir, _make_receipt())
        input_path = _write_input(tmp, _make_minimal_full_context())
        runtime_path = _write_runtime(tmp, _make_minimal_runtime_context())
        result = run_pipeline(input_path, receipts_dir, output_dir, runtime_path=runtime_path)
        with open(result.receipt_path, "r") as f:
            receipt = json.load(f)
        ext = receipt.get("extension", {})
        assert ext.get("boot_hash"), "TC-5 FAIL: boot_hash missing"
        assert ext.get("runtime_hash"), "TC-5 FAIL: runtime_hash missing"
        assert ext.get("runtime_pair_hash"), "TC-5 FAIL: runtime_pair_hash missing"
        assert ext.get("commit_status") == "READY_FOR_COMMIT"
    finally:
        shutil.rmtree(tmp)


def test_tc6_missing_input_raises():
    tmp = tempfile.mkdtemp()
    try:
        receipts_dir, output_dir = _setup_dirs(tmp)
        _write_receipt(receipts_dir, _make_receipt())
        try:
            run_pipeline("/nonexistent/path.json", receipts_dir, output_dir)
            assert False, "TC-6 FAIL: PipelineError not raised"
        except PipelineError as e:
            assert "artifact not found" in str(e)
    finally:
        shutil.rmtree(tmp)
