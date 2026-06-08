"""
test_ledger_verifier.py
AIBA WORM Ledger Verifier 테스트 — EAG-S208-WORM-002
TC-1 ~ TC-6
"""

import sys
import json
import os
import pytest
from pathlib import Path

sys.path.insert(0, "/opt/arss/engine/arss-protocol")
sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/ledger")

import ledger_writer as lw
import ledger_verifier as lv


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    ledger_dir = tmp_path / "ledger"
    obs_dir    = tmp_path / "observation"
    reg_dir    = tmp_path / "registry"
    ledger_dir.mkdir(); obs_dir.mkdir(); reg_dir.mkdir()

    paths = {
        "caddy": ledger_dir / "state_ledger_caddy.jsonl",
        "domi":  ledger_dir / "state_ledger_domi.jsonl",
        "jeni":  ledger_dir / "state_ledger_jeni.jsonl",
    }
    manifest  = ledger_dir / "ledger_manifest.jsonl"
    obs_alert = obs_dir / "observation_alerts.jsonl"
    token_reg = reg_dir / "ledger_tokens.json"

    for mod in (lw, lv):
        monkeypatch.setattr(mod, "LEDGER_DIR",    ledger_dir, raising=False)
        monkeypatch.setattr(mod, "OBSERVATION_DIR", obs_dir,  raising=False)
        monkeypatch.setattr(mod, "LEDGER_PATHS",  paths,      raising=False)
        monkeypatch.setattr(mod, "MANIFEST_PATH", manifest,   raising=False)
        monkeypatch.setattr(mod, "OBS_ALERT_PATH", obs_alert, raising=False)

    monkeypatch.setattr(lw, "LEDGER_TOKEN_REGISTRY", token_reg)
    monkeypatch.setattr(lw, "OBS_LOG_PATH", obs_dir / "observation_log.jsonl")
    monkeypatch.setattr(lw, "_ledger_locks", {
        "caddy": __import__("threading").Lock(),
        "domi":  __import__("threading").Lock(),
        "jeni":  __import__("threading").Lock(),
        "manifest": __import__("threading").Lock(),
    })

    return {"paths": paths, "manifest": manifest, "token_reg": token_reg}


def _setup_all(tmp_env, session="S208", chain_tip="25c261e"):
    for actor in ["caddy", "domi", "jeni"]:
        lw.initialize_genesis(actor, session, chain_tip)
    tokens = {}
    for actor in ["caddy", "domi", "jeni"]:
        tid = f"LT-{actor.upper()}-TEST"
        lw.register_ledger_token(tid, actor, session)
        tokens[actor] = tid
    return tokens


# ── TC-1: 정상 체인 전체 검증 PASS ───────────────────────────────────────────

def test_tc1_verify_chain_pass(tmp_env):
    """TC-1: 정상 append 후 verify_chain PASS"""
    tokens = _setup_all(tmp_env)
    for i in range(3):
        lw.append_entry("domi", "DESIGN_PROPOSAL", f"p{i}", "S208", "25c261e", tokens["domi"])

    result = lv.verify_chain("domi")
    assert result["status"] == "PASS"
    assert result["entries"] == 4  # GENESIS + 3


# ── TC-2: 중간 엔트리 변조 탐지 ──────────────────────────────────────────────

def test_tc2_tampered_entry_detected(tmp_env):
    """TC-2: seq=1 엔트리 payload_hash 변조 → FAIL"""
    tokens = _setup_all(tmp_env)
    lw.append_entry("caddy", "EXEC_SCOPED", "original", "S208", "25c261e", tokens["caddy"])

    path = lw.LEDGER_PATHS["caddy"]
    entries = lw._read_all_entries(path)
    entries[1]["payload_hash"] = "TAMPERED"
    # entry_hash는 그대로 유지 (변조 상황 재현)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    result = lv.verify_chain("caddy")
    assert result["status"] == "FAIL"
    assert "TAMPERED" in result["reason"]


# ── TC-3: 삭제 엔트리 탐지 ───────────────────────────────────────────────────

def test_tc3_deleted_entry_detected(tmp_env):
    """TC-3: 중간 엔트리 삭제 → seq gap으로 FAIL"""
    tokens = _setup_all(tmp_env)
    for i in range(3):
        lw.append_entry("jeni", "TRUST_READY", f"p{i}", "S208", "25c261e", tokens["jeni"])

    path = lw.LEDGER_PATHS["jeni"]
    entries = lw._read_all_entries(path)
    # seq=1 엔트리 삭제 (GENESIS=0, seq1=삭제, seq2~3 유지)
    entries_without_1 = [e for e in entries if e.get("seq") != 1]
    with open(path, "w") as f:
        for e in entries_without_1:
            f.write(json.dumps(e) + "\n")

    result = lv.verify_chain("jeni")
    assert result["status"] == "FAIL"
    assert "SEQ" in result["reason"] or "HASH" in result["reason"]


# ── TC-4: SESSION_FREEZE 이후 엔트리 이상 탐지 ────────────────────────────

def test_tc4_entry_after_freeze_detected(tmp_env):
    """TC-4: manifest에 SESSION_FREEZE 후 강제 엔트리 삽입 → verify_manifest FAIL"""
    tokens = _setup_all(tmp_env)
    lw.append_entry("domi", "DESIGN_PROPOSAL", "p1", "S208", "25c261e", tokens["domi"])

    # SESSION_FREEZE 기록
    lw.append_session_freeze("S208", "EAG-S208-WORM-001", "25c261e")

    # manifest에 강제 엔트리 삽입 (chattr +a 없는 환경에서 변조 시뮬레이션)
    manifest_entries = lw._read_all_entries(lw.MANIFEST_PATH)
    extra = {
        "seq": manifest_entries[-1]["seq"] + 1,
        "timestamp": "2099-01-01T00:00:00+09:00",
        "session": "S208",
        "caddy_head": "fake",
        "domi_head": "fake",
        "jeni_head": "fake",
        "prev_hash": manifest_entries[-1]["entry_hash"],
        "entry_hash": "0" * 64,
    }
    with open(lw.MANIFEST_PATH, "a") as f:
        f.write(json.dumps(extra) + "\n")

    result = lv.verify_manifest()
    assert result["status"] == "FAIL"
    assert "FREEZE" in result["reason"] or "TAMPERED" in result["reason"]


# ── TC-5: manifest head mismatch FAIL ────────────────────────────────────────

def test_tc5_manifest_head_mismatch(tmp_env):
    """TC-5: 장부에 직접 append 후 manifest 미갱신 → head mismatch FAIL"""
    tokens = _setup_all(tmp_env)
    lw.append_entry("domi", "DESIGN_PROPOSAL", "p1", "S208", "25c261e", tokens["domi"])

    # domi 장부에 manifest 갱신 없이 직접 엔트리 강제 삽입
    path = lw.LEDGER_PATHS["domi"]
    entries = lw._read_all_entries(path)
    last = entries[-1]
    fake_entry = {
        "ledger_id": "domi",
        "seq": last["seq"] + 1,
        "timestamp": "2099-01-01T00:00:00+09:00",
        "actor": "domi",
        "action_type": "FAKE",
        "payload_hash": "0" * 64,
        "payload_ref": "FAKE",
        "prev_hash": last["entry_hash"],
        "session": "S208",
        "chain_tip": "25c261e",
        "signature_version": "v1",
    }
    fake_entry["entry_hash"] = lv._compute_entry_hash(fake_entry)
    with open(path, "a") as f:
        f.write(json.dumps(fake_entry) + "\n")

    # manifest는 갱신 안 됨 → head mismatch
    result = lv.verify_manifest()
    assert result["status"] == "FAIL"
    assert "HEAD_MISMATCH" in result["reason"]


# ── TC-6: freeze 이후 엔트리 존재 → verify_manifest FAIL ──────────────────

def test_tc6_manifest_freeze_integrity(tmp_env):
    """TC-6: SESSION_FREEZE 후 manifest 정상 동결 확인"""
    tokens = _setup_all(tmp_env)
    lw.append_entry("caddy", "EXEC_SCOPED", "p1", "S208", "25c261e", tokens["caddy"])
    lw.append_session_freeze("S208", "EAG-S208-WORM-001", "25c261e")

    # 정상 케이스: FREEZE 후 manifest verify PASS
    result = lv.verify_manifest()
    assert result["status"] == "PASS"
    assert result["frozen"] is True
