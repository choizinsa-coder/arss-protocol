"""
test_adr_store.py — ADR Authority Store 검증 (EAG-S350-IAPG-ADR-STORE-001)
실제 장부(GENESIS+ADR-001)는 읽기전용 검증, 변조·fail-closed·복구 시나리오는 tmp_path 사용.
"""
import json
import importlib.util
from pathlib import Path

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
_spec = importlib.util.spec_from_file_location(
    "adr_store", str(Path(ARSS_ROOT) / "tools" / "adr" / "adr_store.py"))
adr_store = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adr_store)


# ---- 실제 부트스트랩 장부 (읽기전용) ----

def test_real_ledger_genesis_and_adr001():
    entries = adr_store._read_all_entries(adr_store.ADR_LEDGER_PATH)
    assert len(entries) >= 2
    g = entries[0]
    assert g["seq"] == 0
    assert g["prev_hash"] == adr_store.GENESIS_PREV_HASH
    assert g["record_type"] == "GENESIS"
    assert adr_store._compute_entry_hash(g) == g["entry_hash"]
    a1 = entries[1]
    assert a1["adr_id"] == "ADR-001"
    assert a1["prev_hash"] == g["entry_hash"]
    assert adr_store._compute_entry_hash(a1) == a1["entry_hash"]


def test_real_ledger_chain_pass():
    r = adr_store.verify_adr_chain(adr_store.ADR_LEDGER_PATH)
    assert r["status"] == adr_store.RC_PASS


def test_adr001_self_reference_guard():
    a1 = adr_store.get_adr_state("ADR-001")
    assert a1 is not None
    assert a1["approval"]["eag_id"] == "EAG-S350-IAPG-ADR-STORE-001"
    assert a1["approval"].get("content_ref") != "ADR-001"
    assert "external_origin_evidence" in a1
    assert a1["external_origin_evidence"]["eag_id"] == "EAG-S350-IAPG-ADR-STORE-001"
    assert len(a1["external_origin_evidence"]["sha256"]) == 64
    assert "self_reference_guard" in a1


def test_adr001_evidence_chain_fields():
    a1 = adr_store.get_adr_state("ADR-001")
    assert a1["proposal"]["author"] == "domi"
    assert a1["verification"]["verifier"] == "jeni"
    assert a1["verification"]["result"] == "TRUST_READY"
    assert a1["approval"]["approver"] == "beo"
    assert a1["canonical_record"]["status"] == adr_store.STATUS_EFFECTIVE


# ---- 변조 탐지 / fail-closed / 복구 (tmp) ----

def _bootstrap_tmp(tmp_path):
    ledger = tmp_path / "adr_ledger.jsonl"
    adr_store.append_entry({"record_type": "GENESIS", "adr_id": "GENESIS", "note": "t"}, path=ledger)
    return ledger


def test_tamper_detection(tmp_path):
    ledger = _bootstrap_tmp(tmp_path)
    adr_store.append_entry({"record_type": "ADR", "adr_id": "ADR-001", "title": "t"}, path=ledger)
    assert adr_store.verify_adr_chain(ledger)["status"] == adr_store.RC_PASS
    lines = ledger.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1])
    e["title"] = "TAMPERED"
    lines[1] = json.dumps(e, ensure_ascii=False)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = adr_store.verify_adr_chain(ledger)
    assert r["status"] == adr_store.RC_FAIL
    assert "TAMPERED" in r["reason"]


def test_prev_hash_break(tmp_path):
    ledger = _bootstrap_tmp(tmp_path)
    adr_store.append_entry({"record_type": "ADR", "adr_id": "ADR-001"}, path=ledger)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1])
    e["prev_hash"] = "0" * 64
    filtered = {k: v for k, v in e.items() if k != "entry_hash"}
    e["entry_hash"] = adr_store._sha256(json.dumps(filtered, sort_keys=True, ensure_ascii=False))
    lines[1] = json.dumps(e, ensure_ascii=False)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = adr_store.verify_adr_chain(ledger)
    assert r["status"] == adr_store.RC_FAIL
    assert "PREV_HASH_MISMATCH" in r["reason"]


def test_fail_closed_append(tmp_path):
    ledger = _bootstrap_tmp(tmp_path)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[0])
    e["entry_hash"] = "deadbeef" * 8
    lines[0] = json.dumps(e, ensure_ascii=False)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = adr_store.append_entry({"record_type": "ADR", "adr_id": "ADR-001"}, path=ledger)
    assert r["status"] == adr_store.RC_FAIL
    assert "FAIL_CLOSED_PRECHECK" in r["reason"]


def test_supersede(tmp_path):
    ledger = _bootstrap_tmp(tmp_path)
    adr_store.append_entry({"record_type": "ADR", "adr_id": "ADR-001", "title": "old",
                            "canonical_record": {"status": adr_store.STATUS_EFFECTIVE, "superseded_by": None}}, path=ledger)
    adr_store.append_entry({"record_type": "ADR", "adr_id": "ADR-002", "title": "new",
                            "canonical_record": {"status": adr_store.STATUS_EFFECTIVE, "superseded_by": None}}, path=ledger)
    adr_store.supersede("ADR-001", "ADR-002", path=ledger)
    st = adr_store.get_adr_state("ADR-001", path=ledger)
    assert st["status"] == adr_store.STATUS_SUPERSEDED
    assert st["superseded_by"] == "ADR-002"
    assert adr_store.verify_adr_chain(ledger)["status"] == adr_store.RC_PASS


def test_sovereign_override_and_gated_resume(tmp_path):
    ledger = _bootstrap_tmp(tmp_path)
    ov = adr_store.sovereign_override_initiate("integrity failure drill", approver="beo", eag_id="EAG-TEST", dir_path=tmp_path)
    assert ov["quarantined"] is True
    assert adr_store.is_quarantined(tmp_path) is True
    r = adr_store.append_entry({"record_type": "ADR", "adr_id": "ADR-001"}, path=ledger)
    assert r["status"] == adr_store.RC_FAIL and r["reason"] == adr_store.RC_QUARANTINED
    assert (tmp_path / "adr_recovery_log.jsonl").exists()
    assert len(adr_store._read_all_entries(ledger)) == 1
    assert adr_store.resume_after_recovery(False, path=ledger, dir_path=tmp_path)["status"] == adr_store.RC_FAIL
    res = adr_store.resume_after_recovery(True, path=ledger, dir_path=tmp_path)
    assert res["status"] == "RESUMED"
    assert adr_store.is_quarantined(tmp_path) is False
    r2 = adr_store.append_entry({"record_type": "ADR", "adr_id": "ADR-001"}, path=ledger)
    assert r2["status"] == adr_store.RC_PASS
