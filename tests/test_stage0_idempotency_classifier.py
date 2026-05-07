# tests/test_stage0_idempotency_classifier.py
# PT-S73-003 Stage 0 PRE_DELTA_IDEMPOTENCY_GATE -- TC-1 ~ TC-10
import os
import json
import pytest
import tempfile
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.delta_context.stage0_idempotency_classifier import (
    classify_stage0,
    _LOCKED_FAIL_SESSIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_locked_sessions():
    """각 테스트 전후 Race Condition in-process lock 초기화."""
    _LOCKED_FAIL_SESSIONS.clear()
    yield
    _LOCKED_FAIL_SESSIONS.clear()


@pytest.fixture
def tmp_dirs():
    """임시 디렉토리 구조 생성."""
    base = tempfile.mkdtemp()
    delta_log_base = os.path.join(base, "DELTA_LOG")
    tx_base        = os.path.join(base, "DELTA_LOG", "transactions")
    commit_base    = os.path.join(base, "DELTA_LOG", "commits")
    os.makedirs(tx_base,     exist_ok=True)
    os.makedirs(commit_base, exist_ok=True)
    yield {
        "base":        base,
        "delta_log":   delta_log_base,
        "tx_base":     tx_base,
        "commit_base": commit_base,
    }
    shutil.rmtree(base)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION = 99
DOMAINS = ["system"]


def _make_delta_dir(dirs, session=SESSION, domain="system"):
    path = os.path.join(dirs["delta_log"], domain, f"S{session}")
    os.makedirs(path, exist_ok=True)


def _make_tx(dirs, session=SESSION, data=None, raw=None):
    path = os.path.join(dirs["tx_base"], f"TX-S{session}.json")
    if raw is not None:
        with open(path, "w") as f:
            f.write(raw)
    else:
        if data is None:
            data = {"session_number": session, "domain": "system"}
        with open(path, "w") as f:
            json.dump(data, f)
    return path


def _make_commit(dirs, session=SESSION, data=None, raw=None):
    path = os.path.join(dirs["commit_base"], f"COMMIT-S{session}.json")
    if raw is not None:
        with open(path, "w") as f:
            f.write(raw)
    else:
        if data is None:
            data = {"session_number": session}
        with open(path, "w") as f:
            json.dump(data, f)
    return path


def _call(dirs, session=SESSION, domains=None,
          expected_delta_hash=None, expected_commit_hash=None):
    if domains is None:
        domains = DOMAINS
    return classify_stage0(
        session_number=session,
        domains=domains,
        delta_log_base=dirs["delta_log"],
        tx_base_path=dirs["tx_base"],
        commit_base_path=dirs["commit_base"],
        expected_delta_hash=expected_delta_hash,
        expected_commit_hash=expected_commit_hash,
    )


# ---------------------------------------------------------------------------
# TC-1: DELTA valid + COMMIT valid -> COMPLETED -> ALLOW_ALREADY_COMPLETED
# ---------------------------------------------------------------------------
def test_tc1_completed(tmp_dirs):
    _make_delta_dir(tmp_dirs)
    _make_tx(tmp_dirs)
    _make_commit(tmp_dirs)

    result = _call(tmp_dirs)

    assert result["state"] == "COMPLETED"
    assert result["gate"]  == "ALLOW_ALREADY_COMPLETED"
    assert result["stage"] == "PRE_DELTA_IDEMPOTENCY_GATE"


# ---------------------------------------------------------------------------
# TC-2: DELTA valid + COMMIT missing -> INVALID -> FAIL_CLOSED
# ---------------------------------------------------------------------------
def test_tc2_invalid(tmp_dirs):
    _make_delta_dir(tmp_dirs)
    _make_tx(tmp_dirs)
    # commit 파일 생성 안 함

    result = _call(tmp_dirs)

    assert result["state"] == "INVALID"
    assert result["gate"]  == "FAIL_CLOSED"


# ---------------------------------------------------------------------------
# TC-3: DELTA missing + COMMIT valid -> PARTIAL_STATE -> FAIL_CLOSED
# ---------------------------------------------------------------------------
def test_tc3_partial_state(tmp_dirs):
    # delta 디렉토리/TX 없음
    _make_commit(tmp_dirs)

    result = _call(tmp_dirs)

    assert result["state"] == "PARTIAL_STATE"
    assert result["gate"]  == "FAIL_CLOSED"


# ---------------------------------------------------------------------------
# TC-4: DELTA missing + COMMIT missing -> NOT_STARTED -> ALLOW_NEW_RUN
# ---------------------------------------------------------------------------
def test_tc4_not_started(tmp_dirs):
    result = _call(tmp_dirs)

    assert result["state"] == "NOT_STARTED"
    assert result["gate"]  == "ALLOW_NEW_RUN"


# ---------------------------------------------------------------------------
# TC-5: 판정 중 예외 발생 -> UNKNOWN -> FAIL_CLOSED
# ---------------------------------------------------------------------------
def test_tc5_exception_unknown(tmp_dirs, monkeypatch):
    _make_delta_dir(tmp_dirs)
    _make_tx(tmp_dirs)
    _make_commit(tmp_dirs)

    import tools.delta_context.stage0_idempotency_classifier as mod

    def _raise(*a, **kw):
        raise RuntimeError("simulated integrity error")

    monkeypatch.setattr(mod, "_check_file_integrity", _raise)

    result = _call(tmp_dirs)

    assert result["state"] == "UNKNOWN"
    assert result["gate"]  == "FAIL_CLOSED"
    assert "INTEGRITY_CHECK_EXCEPTION" in result["reason"]


# ---------------------------------------------------------------------------
# TC-6: COMMIT exists but zero-byte -> UNKNOWN -> FAIL_CLOSED
# ---------------------------------------------------------------------------
def test_tc6_commit_zero_byte(tmp_dirs):
    _make_delta_dir(tmp_dirs)
    _make_tx(tmp_dirs)

    # zero-byte commit
    commit_path = os.path.join(tmp_dirs["commit_base"], f"COMMIT-S{SESSION}.json")
    open(commit_path, "w").close()

    result = _call(tmp_dirs)

    assert result["state"] == "UNKNOWN"
    assert result["gate"]  == "FAIL_CLOSED"
    assert "ZERO_BYTE" in result["reason"]


# ---------------------------------------------------------------------------
# TC-7: COMMIT exists but malformed (invalid JSON) -> UNKNOWN -> FAIL_CLOSED
# ---------------------------------------------------------------------------
def test_tc7_commit_malformed(tmp_dirs):
    _make_delta_dir(tmp_dirs)
    _make_tx(tmp_dirs)
    _make_commit(tmp_dirs, raw="{NOT VALID JSON:::}")

    result = _call(tmp_dirs)

    assert result["state"] == "UNKNOWN"
    assert result["gate"]  == "FAIL_CLOSED"
    assert "MALFORMED" in result["reason"]


# ---------------------------------------------------------------------------
# TC-8: DELTA (TX) exists but malformed -> UNKNOWN -> FAIL_CLOSED
# ---------------------------------------------------------------------------
def test_tc8_delta_malformed(tmp_dirs):
    _make_delta_dir(tmp_dirs)
    _make_tx(tmp_dirs, raw="{NOT VALID JSON:::}")
    _make_commit(tmp_dirs)

    result = _call(tmp_dirs)

    assert result["state"] == "UNKNOWN"
    assert result["gate"]  == "FAIL_CLOSED"
    assert "MALFORMED" in result["reason"]


# ---------------------------------------------------------------------------
# TC-9: integrity/hash mismatch -> UNKNOWN -> FAIL_CLOSED
# hash_check.delta.result == "MISMATCH" 확인
# ---------------------------------------------------------------------------
def test_tc9_hash_mismatch(tmp_dirs):
    _make_delta_dir(tmp_dirs)
    _make_tx(tmp_dirs, data={
        "session_number": SESSION,
        "domain": "system",
        "hash": "abc123",
    })
    _make_commit(tmp_dirs)

    result = _call(tmp_dirs, expected_delta_hash="WRONG_HASH")

    assert result["state"] == "UNKNOWN"
    assert result["gate"]  == "FAIL_CLOSED"
    assert result["hash_check"]["delta"]["result"] == "MISMATCH"
    assert "DELTA_HASH_MISMATCH" in result["reason"]


# ---------------------------------------------------------------------------
# TC-10: PARTIAL_STATE 감지 후 동일 프로세스 내 DELTA 추가 -> COMPLETED 승격 금지
# Race Condition Defense (in-process lock) 검증
# ---------------------------------------------------------------------------
def test_tc10_race_condition_no_upgrade(tmp_dirs):
    # 1차 판정: commit만 존재 -> PARTIAL_STATE
    _make_commit(tmp_dirs)
    result1 = _call(tmp_dirs)
    assert result1["state"] == "PARTIAL_STATE"
    assert result1["gate"]  == "FAIL_CLOSED"

    # 외부 간섭 시뮬레이션: delta 파일 추가
    _make_delta_dir(tmp_dirs)
    _make_tx(tmp_dirs)

    # 동일 프로세스 내 재판정 -> FAIL_CLOSED 유지, COMPLETED 승격 금지
    result2 = _call(tmp_dirs)
    assert result2["gate"]  == "FAIL_CLOSED"
    assert result2["state"] != "COMPLETED"
    assert result2["reason"] == "RACE_CONDITION_LOCKED"
