"""
PT-S69-002: TX-S69 INCOMPLETE Recovery (CASE-B: PENDING_VOID)
EAG-1/2 비오(Joshua) 승인 완료
"""
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path("/opt/arss/engine/arss-protocol")
TX_PATH = BASE / "DELTA_LOG/transactions/TX-S69.json"
INDEX_PATH = BASE / "DELTA_LOG/INDEX.json"
AGENT_FOCUS_SRC = BASE / "DELTA_LOG/agent_focus/S69"
QUARANTINE_DST = BASE / "SNAPSHOT_LOG/quarantine/agent_focus_S69"

KST = timezone(timedelta(hours=9))

def step1_void_tx():
    """TX-S69.json VOID 전환"""
    if not TX_PATH.exists():
        raise FileNotFoundError("TX-S69.json not found — STOP")
    with open(TX_PATH) as f:
        tx = json.load(f)
    if tx.get("status") != "INCOMPLETE":
        raise ValueError(f"Unexpected status: {tx.get('status')} — STOP")
    tx["original_status"] = "INCOMPLETE"
    tx["status"] = "VOID"
    tx["void_reason"] = "IMPORT_ERROR_DELTA_WRITER"
    tx["voided_at"] = datetime.now(KST).isoformat()
    tx["integrity"] = "UNVERIFIED_PARTIAL_WRITE"
    with open(TX_PATH, "w") as f:
        json.dump(tx, f, indent=2, ensure_ascii=False)
    print("[STEP1] TX-S69.json → VOID: OK")

def step2_sync_index():
    """INDEX.json TX-S69 entry 동기화"""
    if not INDEX_PATH.exists():
        raise FileNotFoundError("INDEX.json not found — STOP")
    with open(INDEX_PATH) as f:
        idx = json.load(f)
    transactions = idx.get("transactions", [])
    entry = next((t for t in transactions if t.get("tx_id") == "TX-S69"), None)
    if entry is None:
        entry = {"tx_id": "TX-S69", "status": "VOID"}
        transactions.append(entry)
    else:
        entry["status"] = "VOID"
    idx["transactions"] = transactions
    with open(INDEX_PATH, "w") as f:
        json.dump(idx, f, indent=2, ensure_ascii=False)
    print("[STEP2] INDEX.json TX-S69 → VOID: OK")

def step3_quarantine_agent_focus():
    """agent_focus/S69 → SNAPSHOT_LOG/quarantine/agent_focus_S69 이동"""
    if not AGENT_FOCUS_SRC.exists():
        raise FileNotFoundError("agent_focus/S69 not found — STOP")
    if QUARANTINE_DST.exists():
        raise FileExistsError(f"Quarantine dst already exists: {QUARANTINE_DST} — STOP")
    shutil.move(str(AGENT_FOCUS_SRC), str(QUARANTINE_DST))
    print(f"[STEP3] agent_focus/S69 → quarantine: OK")

def step4_validate():
    """FAIL-CLOSED validator"""
    errors = []
    with open(TX_PATH) as f:
        tx = json.load(f)
    if tx.get("status") != "VOID":
        errors.append("TX status != VOID")
    if tx.get("original_status") != "INCOMPLETE":
        errors.append("TX original_status != INCOMPLETE")
    if not tx.get("void_reason"):
        errors.append("TX void_reason missing")
    if not tx.get("voided_at"):
        errors.append("TX voided_at missing")
    with open(INDEX_PATH) as f:
        idx = json.load(f)
    entry = next((t for t in idx.get("transactions", []) if t.get("tx_id") == "TX-S69"), None)
    if entry is None:
        errors.append("INDEX TX-S69 entry missing")
    elif entry.get("status") != "VOID":
        errors.append("INDEX TX-S69 status != VOID")
    if AGENT_FOCUS_SRC.exists():
        errors.append("agent_focus/S69 still in active path")
    if not QUARANTINE_DST.exists():
        errors.append("quarantine/agent_focus_S69 not found")
    if errors:
        raise RuntimeError(f"VALIDATION FAILED: {errors}")
    print("[STEP4] Validation: ALL PASS")

def run():
    print("=== TX-S69 Recovery START ===")
    step1_void_tx()
    step2_sync_index()
    step3_quarantine_agent_focus()
    step4_validate()
    print("=== TX-S69 Recovery COMPLETE ===")

if __name__ == "__main__":
    run()
