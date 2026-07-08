"""
adr_store.py
AIBA ADR (의사결정) Authority Store — EAG-S350-IAPG-ADR-STORE-001

IAPG 의사결정 도메인의 독립 권위원천(Authority) 저장소.
세션 저널(tools/ledger/ledger_verifier.py)의 검증된 불변 패턴을 독립 복제한다.
  - append-only jsonl
  - prev_hash 해시 체인 (각 entry.prev_hash == 직전 entry.entry_hash)
  - entry_hash 재계산 기반 변조 탐지 (SHA256, sort_keys, ensure_ascii=False, entry_hash 필드 제외)
  - 무결성 실패 시 정상 write/activation 경로 fail-closed

EAG-S350 설계 제약(준수):
  - 불변성 Anchor는 이 저장소 자체의 hash chain이며, git history/rollback을 불변성 보장 수단으로 인정하지 않는다.
  - ADR Authority와 SESSION_CONTEXT(프로젝트상태) Authority는 서로 다른 도메인의 독립 권위원천이다.
  - 기존 세션 저널/ledger 파일은 수정·재사용하지 않는다(G1-FRZ-001 동결).
  - 기존 context/governance/decisions.json은 변환·부활·수정하지 않는다(legacy read-only archive).
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
ADR_DIR = Path(ARSS_ROOT) / "context" / "adr"
ADR_LEDGER_PATH = ADR_DIR / "adr_ledger.jsonl"
ADR_RECOVERY_LOG_PATH = ADR_DIR / "adr_recovery_log.jsonl"
QUARANTINE_FLAG_NAME = "adr_store.QUARANTINED"

GENESIS_PREV_HASH = "0" * 64
SCHEMA_VERSION = "adr_v1"
KST = timezone(timedelta(hours=9))

# 결과 코드
RC_PASS = "PASS"
RC_FAIL = "FAIL"
RC_GENESIS_SEQ_MISMATCH = "GENESIS_SEQ_MISMATCH"
RC_GENESIS_PREV_HASH_MISMATCH = "GENESIS_PREV_HASH_MISMATCH"
RC_SEQ_GAP = "SEQ_GAP"
RC_PREV_HASH_MISMATCH = "PREV_HASH_MISMATCH"
RC_ENTRY_HASH_TAMPERED = "ENTRY_HASH_TAMPERED"
RC_LEDGER_EMPTY = "LEDGER_EMPTY_OR_NOT_FOUND"
RC_QUARANTINED = "STORE_QUARANTINED"

# lifecycle 상태 (단방향)
STATUS_DRAFT = "DRAFT"
STATUS_VERIFIED = "VERIFIED"
STATUS_APPROVED = "APPROVED"
STATUS_EFFECTIVE = "EFFECTIVE"
STATUS_SUPERSEDED = "SUPERSEDED"


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(KST).isoformat()


def _compute_entry_hash(entry: dict) -> str:
    """세션 저널 _compute_entry_hash 계약 승계: entry_hash 필드 제외, sort_keys, ensure_ascii=False."""
    filtered = {k: v for k, v in entry.items() if k != "entry_hash"}
    return _sha256(json.dumps(filtered, sort_keys=True, ensure_ascii=False))


def _read_all_entries(path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def is_quarantined(dir_path=ADR_DIR) -> bool:
    return (Path(dir_path) / QUARANTINE_FLAG_NAME).exists()


def verify_adr_chain(path=ADR_LEDGER_PATH) -> dict:
    """ADR 장부 전체 체인 무결성 검증. 세션 저널 verify_chain 패턴 복제."""
    entries = _read_all_entries(path)
    if not entries:
        return {"status": RC_FAIL, "reason": RC_LEDGER_EMPTY}
    for i, entry in enumerate(entries):
        seq = entry.get("seq")
        if i == 0:
            if seq != 0:
                return {"status": RC_FAIL, "reason": "%s: expected=0 got=%s" % (RC_GENESIS_SEQ_MISMATCH, seq), "entry_seq": seq}
            if entry.get("prev_hash") != GENESIS_PREV_HASH:
                return {"status": RC_FAIL, "reason": RC_GENESIS_PREV_HASH_MISMATCH, "entry_seq": seq}
        else:
            exp_seq = entries[i - 1].get("seq", -1) + 1
            if seq != exp_seq:
                return {"status": RC_FAIL, "reason": "%s: expected=%s got=%s" % (RC_SEQ_GAP, exp_seq, seq), "entry_seq": seq}
            if entry.get("prev_hash") != entries[i - 1].get("entry_hash"):
                return {"status": RC_FAIL, "reason": "%s at seq=%s" % (RC_PREV_HASH_MISMATCH, seq), "entry_seq": seq}
        if _compute_entry_hash(entry) != entry.get("entry_hash"):
            return {"status": RC_FAIL, "reason": "%s at seq=%s" % (RC_ENTRY_HASH_TAMPERED, seq), "entry_seq": seq}
    return {"status": RC_PASS, "entries": len(entries)}


def _next_seq_and_prev(path):
    entries = _read_all_entries(path)
    if not entries:
        return 0, GENESIS_PREV_HASH
    last = entries[-1]
    return last.get("seq", -1) + 1, last.get("entry_hash")


def append_entry(entry: dict, path=ADR_LEDGER_PATH, verify_first: bool = True) -> dict:
    """fail-closed append. quarantine 상태에서는 정상 기입 거부(Sovereign Override 복구 경로만 허용)."""
    path = Path(path)
    if is_quarantined(path.parent):
        return {"status": RC_FAIL, "reason": RC_QUARANTINED}
    if verify_first and path.exists() and _read_all_entries(path):
        chk = verify_adr_chain(path)
        if chk["status"] != RC_PASS:
            return {"status": RC_FAIL, "reason": "FAIL_CLOSED_PRECHECK:%s" % chk.get("reason")}
    seq, prev = _next_seq_and_prev(path)
    entry = dict(entry)
    entry["seq"] = seq
    entry["prev_hash"] = prev
    entry["schema_version"] = SCHEMA_VERSION
    entry["entry_hash"] = _compute_entry_hash(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    post = verify_adr_chain(path)
    return {"status": post["status"], "seq": seq, "entry_hash": entry["entry_hash"], "post_verify": post["status"]}


def get_adr_state(adr_id: str, path=ADR_LEDGER_PATH):
    """append 이벤트를 fold하여 ADR 현재 상태 산출(장부가 Authority, 현재상태는 파생)."""
    state = None
    for e in _read_all_entries(path):
        if e.get("adr_id") != adr_id:
            continue
        if e.get("record_type") == "ADR":
            state = dict(e)
            cr = e.get("canonical_record", {}) or {}
            state["status"] = e.get("status") or cr.get("status")
            state["superseded_by"] = cr.get("superseded_by")
        elif e.get("record_type") == "STATUS_CHANGE" and state is not None:
            state["status"] = e.get("new_status", state.get("status"))
            if e.get("superseded_by"):
                state["superseded_by"] = e.get("superseded_by")
    return state


def supersede(old_adr_id: str, new_adr_id: str, path=ADR_LEDGER_PATH) -> dict:
    """정정·폐기 시 신규 ADR로 supersede. 원본은 수정하지 않고 상태전환을 신규 append 이벤트로 기록(WORM)."""
    return append_entry({
        "record_type": "STATUS_CHANGE",
        "adr_id": old_adr_id,
        "new_status": STATUS_SUPERSEDED,
        "superseded_by": new_adr_id,
        "timestamp": _now_iso(),
    }, path=path)


def sovereign_override_initiate(reason: str, approver: str = "beo", eag_id=None, dir_path=ADR_DIR) -> dict:
    """
    Beo Sovereign Override — 독립 비상 복구 경로.
    손상 장부의 정상상태 판정에 의존하지 않고 호출 가능(체인 검증 결과와 무관).
    정상 ADR을 위조·생성하지 않는다: 별도 recovery log에만 기록하고 저장소를 QUARANTINE 표시.
    권한 범위: 격리→복구→재검증 개시. 정상 재개는 resume_after_recovery() 게이트 필수.
    """
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    rec = {
        "record_type": "SOVEREIGN_OVERRIDE",
        "action": "QUARANTINE_INITIATE",
        "reason": reason,
        "approver": approver,
        "eag_id": eag_id,
        "timestamp": _now_iso(),
    }
    with open(dir_path / "adr_recovery_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    (dir_path / QUARANTINE_FLAG_NAME).write_text(
        "QUARANTINED %s by %s eag=%s\n" % (_now_iso(), approver, eag_id), encoding="utf-8")
    return {"status": "QUARANTINE_INITIATED", "quarantined": True}


def resume_after_recovery(gate_passed: bool, path=ADR_LEDGER_PATH, dir_path=ADR_DIR) -> dict:
    """
    복구 후 정상 재개: 별도 검증 게이트(gate_passed=도미재설계+제니 TRUST_READY+비오 EAG의 외부 판정) +
    장부 체인 PASS 둘 다 충족 시에만 QUARANTINE 해제. Override 자체는 재개를 자동 승인하지 않는다.
    """
    if not gate_passed:
        return {"status": RC_FAIL, "reason": "RECOVERY_GATE_NOT_PASSED"}
    chk = verify_adr_chain(path)
    if chk["status"] != RC_PASS:
        return {"status": RC_FAIL, "reason": "CHAIN_NOT_HEALTHY:%s" % chk.get("reason")}
    flag = Path(dir_path) / QUARANTINE_FLAG_NAME
    if flag.exists():
        flag.unlink()
    return {"status": "RESUMED"}
