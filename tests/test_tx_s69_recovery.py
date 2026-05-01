"""PT-S69-002 TC-1~4"""
import json
import pytest
from pathlib import Path

BASE = Path("/opt/arss/engine/arss-protocol")

def make_tx(status="INCOMPLETE"):
    return {"tx_id": "TX-S69", "status": status}

def make_index(has_entry=True, entry_status="INCOMPLETE"):
    txs = [{"tx_id": "TX-S69", "status": entry_status}] if has_entry else []
    return {"transactions": txs}

def load_rec(tmp_path, af_src, qr_dst):
    import importlib
    import tools.delta_context.tx_recovery as rec
    importlib.reload(rec)
    rec.TX_PATH = tmp_path / "TX-S69.json"
    rec.INDEX_PATH = tmp_path / "INDEX.json"
    rec.AGENT_FOCUS_SRC = af_src
    rec.QUARANTINE_DST = qr_dst
    return rec

# TC-1: INCOMPLETE TX → VOID 변환 → PASS
def test_tc1_void_transition(tmp_path):
    af_src = tmp_path / "agent_focus" / "S69"
    af_src.mkdir(parents=True)
    qr_dst = tmp_path / "quarantine" / "agent_focus_S69"
    (tmp_path / "TX-S69.json").write_text(json.dumps(make_tx("INCOMPLETE")))
    (tmp_path / "INDEX.json").write_text(json.dumps(make_index(True, "INCOMPLETE")))
    rec = load_rec(tmp_path, af_src, qr_dst)
    rec.run()
    tx = json.loads((tmp_path / "TX-S69.json").read_text())
    assert tx["status"] == "VOID"
    assert tx["original_status"] == "INCOMPLETE"
    assert not af_src.exists()
    assert qr_dst.exists()

# TC-2: INDEX entry MISSING → 신규 생성 후 VOID PASS
def test_tc2_index_missing_entry(tmp_path):
    af_src = tmp_path / "agent_focus" / "S69"
    af_src.mkdir(parents=True)
    qr_dst = tmp_path / "quarantine" / "agent_focus_S69"
    (tmp_path / "TX-S69.json").write_text(json.dumps(make_tx("INCOMPLETE")))
    (tmp_path / "INDEX.json").write_text(json.dumps(make_index(has_entry=False)))
    rec = load_rec(tmp_path, af_src, qr_dst)
    rec.run()
    idx = json.loads((tmp_path / "INDEX.json").read_text())
    entry = next(t for t in idx["transactions"] if t["tx_id"] == "TX-S69")
    assert entry["status"] == "VOID"

# TC-3: agent_focus 미이동 → FAIL
def test_tc3_agent_focus_not_moved(tmp_path):
    af_src = tmp_path / "agent_focus" / "S69"
    af_src.mkdir(parents=True)
    qr_dst = tmp_path / "quarantine" / "agent_focus_S69"
    (tmp_path / "TX-S69.json").write_text(json.dumps(make_tx("INCOMPLETE")))
    (tmp_path / "INDEX.json").write_text(json.dumps(make_index(True, "INCOMPLETE")))
    rec = load_rec(tmp_path, af_src, qr_dst)
    rec.step1_void_tx()
    rec.step2_sync_index()
    # step3 미실행
    with pytest.raises(RuntimeError, match="agent_focus/S69 still in active path"):
        rec.step4_validate()

# TC-4: void_reason 누락 → FAIL
def test_tc4_void_reason_missing(tmp_path):
    af_src = tmp_path / "agent_focus" / "S69"
    qr_dst = tmp_path / "quarantine" / "agent_focus_S69"
    qr_dst.mkdir(parents=True)
    (tmp_path / "TX-S69.json").write_text(json.dumps({
        "tx_id": "TX-S69", "status": "VOID",
        "original_status": "INCOMPLETE",
        "voided_at": "2026-05-01T00:00:00+09:00",
        "integrity": "UNVERIFIED_PARTIAL_WRITE"
        # void_reason 누락
    }))
    (tmp_path / "INDEX.json").write_text(json.dumps(make_index(True, "VOID")))
    rec = load_rec(tmp_path, af_src, qr_dst)
    with pytest.raises(RuntimeError, match="void_reason missing"):
        rec.step4_validate()
