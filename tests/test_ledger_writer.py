"""
test_ledger_writer.py
AIBA WORM Ledger Writer 테스트 — EAG-S208-WORM-002
TC-1 ~ TC-8
"""

import sys
import os
import json
import hashlib
import tempfile
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch

# sys.path 설정
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/ledger")

import ledger_writer as lw
import ledger_verifier as lv


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    """임시 디렉토리를 WORM ledger 경로로 교체."""
    ledger_dir = tmp_path / "ledger"
    obs_dir = tmp_path / "observation"
    registry_dir = tmp_path / "registry"
    ledger_dir.mkdir()
    obs_dir.mkdir()
    registry_dir.mkdir()

    paths = {
        "caddy": ledger_dir / "state_ledger_caddy.jsonl",
        "domi":  ledger_dir / "state_ledger_domi.jsonl",
        "jeni":  ledger_dir / "state_ledger_jeni.jsonl",
    }
    manifest = ledger_dir / "ledger_manifest.jsonl"
    obs_log   = obs_dir / "observation_log.jsonl"
    obs_alert = obs_dir / "observation_alerts.jsonl"
    token_reg = registry_dir / "ledger_tokens.json"

    monkeypatch.setattr(lw, "LEDGER_DIR",   ledger_dir)
    monkeypatch.setattr(lw, "OBSERVATION_DIR", obs_dir)
    monkeypatch.setattr(lw, "LEDGER_TOKEN_REGISTRY", token_reg)
    monkeypatch.setattr(lw, "LEDGER_PATHS", paths)
    monkeypatch.setattr(lw, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(lw, "OBS_LOG_PATH",  obs_log)
    monkeypatch.setattr(lw, "OBS_ALERT_PATH", obs_alert)

    # 락 재초기화
    monkeypatch.setattr(lw, "_ledger_locks", {
        "caddy": __import__("threading").Lock(),
        "domi":  __import__("threading").Lock(),
        "jeni":  __import__("threading").Lock(),
        "manifest": __import__("threading").Lock(),
    })

    # lv(ledger_verifier) 모듈도 동일 경로로 패치
    obs_alert = obs_dir / "observation_alerts.jsonl"
    monkeypatch.setattr(lv, "LEDGER_PATHS",   paths)
    monkeypatch.setattr(lv, "MANIFEST_PATH",  manifest)
    monkeypatch.setattr(lv, "OBS_ALERT_PATH", obs_alert)

    return {
        "ledger_dir": ledger_dir,
        "paths": paths,
        "manifest": manifest,
        "token_reg": token_reg,
    }


def _issue_token(tmp_ledger, actor="domi", session="S208", token_id="LT-TEST-001"):
    result = lw.register_ledger_token(token_id, actor, session)
    assert result["ok"]
    return token_id


def _genesis(tmp_ledger, actor="domi"):
    result = lw.initialize_genesis(actor, "S208", "25c261e")
    assert result["ok"]
    return result


# ── TC-1: 정상 append + hash chain 연속성 ──────────────────────────────────

def test_tc1_normal_append_hash_chain(tmp_ledger):
    """TC-1: 정상 append 2회 — hash chain 연속성 검증"""
    _genesis(tmp_ledger, "domi")
    token = _issue_token(tmp_ledger, "domi")

    r1 = lw.append_entry("domi", "DESIGN_PROPOSAL", "payload1", "S208", "25c261e", token)
    assert r1["ok"], r1
    assert r1["seq"] == 1

    r2 = lw.append_entry("domi", "DESIGN_PROPOSAL", "payload2", "S208", "25c261e", token)
    assert r2["ok"], r2
    assert r2["seq"] == 2

    # prev_hash 체인 연결 확인
    entries = lw._read_all_entries(lw.LEDGER_PATHS["domi"])
    assert len(entries) == 3  # GENESIS + 2
    assert entries[1]["prev_hash"] == entries[0]["entry_hash"]
    assert entries[2]["prev_hash"] == entries[1]["entry_hash"]


# ── TC-2: prev_hash 불일치 시 FAIL_CLOSED ──────────────────────────────────

def test_tc2_prev_hash_mismatch_fail_closed(tmp_ledger):
    """TC-2: 장부 파일 직접 변조 → verify_chain FAIL 확인"""
    _genesis(tmp_ledger, "caddy")
    token = _issue_token(tmp_ledger, "caddy", token_id="LT-TEST-002")

    lw.append_entry("caddy", "EXEC_SCOPED", "payload", "S208", "25c261e", token)

    # 장부 중간 엔트리 직접 변조
    path = lw.LEDGER_PATHS["caddy"]
    entries = lw._read_all_entries(path)
    entries[0]["payload_hash"] = "tampered"
    # entry_hash는 그대로 유지 — 원래 hash vs 재계산 hash 불일치 유발
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    result = lv.verify_chain("caddy")
    assert result["status"] == "FAIL"
    assert "HASH" in result["reason"] or "MISMATCH" in result["reason"] or "TAMPERED" in result["reason"]


# ── TC-3: 토큰 없이 Read 허용 ────────────────────────────────────────────────

def test_tc3_read_without_token(tmp_ledger):
    """TC-3: 토큰 없이 장부 Read — 허용 확인"""
    _genesis(tmp_ledger, "jeni")
    token = _issue_token(tmp_ledger, "jeni", token_id="LT-TEST-003")
    lw.append_entry("jeni", "TRUST_READY", "payload", "S208", "25c261e", token)

    # Read는 토큰 없이 직접 파일 읽기 허용
    entries = lw._read_all_entries(lw.LEDGER_PATHS["jeni"])
    assert len(entries) == 2  # GENESIS + 1
    assert entries[0]["action_type"] == "GENESIS"


# ── TC-4: 토큰 없이 Write 차단 ───────────────────────────────────────────────

def test_tc4_write_without_token_denied(tmp_ledger):
    """TC-4: 유효하지 않은 토큰으로 append → FAIL_CLOSED"""
    _genesis(tmp_ledger, "domi")

    result = lw.append_entry("domi", "DESIGN_PROPOSAL", "payload", "S208", "25c261e",
                              "INVALID_TOKEN_ID")
    assert not result["ok"]
    assert "FAIL_CLOSED" in result["error"]
    assert "TOKEN_NOT_FOUND" in result["error"]


# ── TC-5: seq 연속성 검증 ─────────────────────────────────────────────────────

def test_tc5_seq_continuity(tmp_ledger):
    """TC-5: seq 0→1→2→3 연속 append 검증"""
    _genesis(tmp_ledger, "caddy")
    token = _issue_token(tmp_ledger, "caddy", token_id="LT-TEST-005")

    for i in range(3):
        r = lw.append_entry("caddy", "EXEC_SCOPED", f"p{i}", "S208", "25c261e", token)
        assert r["ok"]
        assert r["seq"] == i + 1

    result = lv.verify_chain("caddy")
    assert result["status"] == "PASS"
    assert result["entries"] == 4  # GENESIS + 3


# ── TC-6: manifest 업데이트 정합성 ───────────────────────────────────────────

def test_tc6_manifest_update(tmp_ledger):
    """TC-6: append 후 manifest의 actor_head가 최신 entry_hash와 일치"""
    from ledger_verifier import verify_manifest
    for actor in ["caddy", "domi", "jeni"]:
        lw.initialize_genesis(actor, "S208", "25c261e")
    token = _issue_token(tmp_ledger, "domi")
    lw.append_entry("domi", "DESIGN_PROPOSAL", "payload", "S208", "25c261e", token)

    result = verify_manifest()
    assert result["status"] == "PASS", result


# ── TC-7: SESSION_FREEZE 이후 append FAIL ─────────────────────────────────

def test_tc7_append_after_freeze_fail(tmp_ledger):
    """TC-7: SESSION_FREEZE 기록 후 append 시도 → FAIL_CLOSED"""
    for actor in ["caddy", "domi", "jeni"]:
        lw.initialize_genesis(actor, "S208", "25c261e")
    token = _issue_token(tmp_ledger)

    # SESSION_FREEZE
    freeze_result = lw.append_session_freeze("S208", "EAG-S208-WORM-001", "25c261e")
    assert freeze_result["ok"]

    # Freeze 이후 append 시도
    result = lw.append_entry("domi", "DESIGN_PROPOSAL", "payload", "S208", "25c261e", token)
    assert not result["ok"]
    assert "FROZEN" in result["error"] or "REVOKED" in result["error"]


# ── TC-8: invalid actor token FAIL ───────────────────────────────────────────

def test_tc8_invalid_actor_token(tmp_ledger):
    """TC-8: 다른 에이전트 토큰으로 append 시도 → FAIL_CLOSED (ACTOR_MISMATCH)"""
    _genesis(tmp_ledger, "caddy")
    _genesis(tmp_ledger, "domi")

    # domi 토큰 발급
    domi_token = _issue_token(tmp_ledger, "domi", token_id="LT-TEST-008-DOMI")

    # caddy 장부에 domi 토큰으로 쓰기 시도
    result = lw.append_entry("caddy", "EXEC_SCOPED", "payload", "S208", "25c261e",
                              domi_token)
    assert not result["ok"]
    assert "MISMATCH" in result["error"]
