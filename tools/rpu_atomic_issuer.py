#!/usr/bin/env python3
"""
rpu_atomic_issuer.py — RPU Atomic Issuer v1.0
Single-Path / Fail-Closed / Atomic-Rollback 기반 프로덕션 RPU 발행
EAG-2 Approved: 2026-04-09
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# =============================================================================
# 상수
# =============================================================================
ISSUER_VERSION       = "rpu_atomic_issuer v1.0"
PRODUCTION_SCHEMA    = "ARSS-RPU-1.0"
BASE_DIR             = Path("/opt/arss/engine/arss-protocol")
EVIDENCE_DIR         = BASE_DIR / "evidence"
TOOLS_DIR            = BASE_DIR / "tools"
PROOF_DIR            = BASE_DIR / "proof"
FAILED_DIR           = BASE_DIR / "failed" / "issuer_failures"
TXN_CURRENT_DIR      = EVIDENCE_DIR / ".txn" / "current"
TXN_HISTORY_DIR      = EVIDENCE_DIR / ".txn" / "history"
SCORING_LEDGER_PATH  = EVIDENCE_DIR / "scoring_ledger.json"
LEDGER_PATH          = EVIDENCE_DIR / "ledger.json"
VERIFIER_SCRIPT      = BASE_DIR / "scripts" / "workflow" / "vps_verifier_bridge.py"
GENERATOR_URL        = "http://127.0.0.1:8001/generate"
PROOF_SUMMARY_PATH   = PROOF_DIR / "latest_issue_summary.json"
PROOF_RUNTIME_PATH   = PROOF_DIR / "issue_status_runtime.json"

# Dry-run mock RPU (Step 3 대체용)
DRY_RUN_MOCK_PAYLOAD_HASH = "a" * 64
DRY_RUN_MOCK_CHAIN_HASH   = "b" * 64

# =============================================================================
# 유틸
# =============================================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def run_cmd(cmd: list) -> tuple:
    """명령 실행 → (returncode, stdout, stderr)"""
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def log(msg: str):
    print(f"[{now_iso()}] {msg}", flush=True)

def stop(code: str, detail: str = ""):
    log(f"STOP | {code} | {detail}")
    sys.exit(1)

# =============================================================================
# Step 0 — Precondition Gate
# =============================================================================

def step0_precondition(dry_run: bool):
    log("Step 0: Precondition Gate")

    # 필수 경로 존재 확인
    for p in [EVIDENCE_DIR, PROOF_DIR, FAILED_DIR, TXN_CURRENT_DIR, VERIFIER_SCRIPT]:
        if not p.exists():
            stop("PRECONDITION_FAILED", f"경로 없음: {p}")

    # 이전 미정리 transaction 확인
    leftover = list(TXN_CURRENT_DIR.iterdir())
    if leftover:
        stop("PENDING_TRANSACTION_EXISTS",
             f"미정리 파일: {[f.name for f in leftover]}")

    # generator reachability (dry-run 제외)
    if not dry_run:
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8001/health",
                method="GET"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            stop("GENERATOR_UNREACHABLE", str(e))

    # git fetch origin
    rc, out, err = run_cmd(["git", "-C", str(BASE_DIR), "fetch", "origin"])
    if rc != 0:
        stop("GIT_FETCH_FAILED", err)

    # 원격 대비 behind 확인
    rc, out, _ = run_cmd([
        "git", "-C", str(BASE_DIR),
        "rev-list", "--count", "HEAD..origin/main"
    ])
    if rc == 0 and out.strip() != "0":
        stop("REMOTE_AHEAD_SYNC_REQUIRED",
             f"로컬이 origin/main 대비 {out.strip()} commit behind")

    # working tree clean 확인
    rc, out, _ = run_cmd([
        "git", "-C", str(BASE_DIR), "status", "--porcelain"
    ])
    if out.strip():
        stop("WORKTREE_NOT_CLEAN", f"untracked/staged 존재: {out[:200]}")

    log("Step 0: PASS")


# =============================================================================
# Step 1 — EAG Approval Token 검증
# =============================================================================

def step1_eag(event_file_path: str, approval_token_path: str, session_count: int):
    log("Step 1: EAG Approval Token 검증 (v2.0)")
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from arss_gatekeeper import validate as gk_validate
    result = gk_validate(
        event_file_path=event_file_path,
        approval_token_path=approval_token_path,
        session_count=session_count
    )
    if not result.approved:
        stop("EAG_TOKEN_INVALID", f"gatekeeper REJECT: {result.reason} | receipt: {result.receipt_path}")
    log(f"Step 1: PASS | receipt: {result.receipt_path}")


# =============================================================================
# Step 2 — Dual-Source prev_hash Cross-Check
# =============================================================================

def step2_dual_source() -> str:
    """확정된 prev_chain_hash 반환"""
    log("Step 2: Dual-Source prev_hash Cross-Check")

    # Source A: scoring_ledger
    ledger = load_json(SCORING_LEDGER_PATH)
    ledger_chain_tip = ledger.get("chain_tip", "")
    ledger_last_rpu  = ledger.get("last_rpu", "")

    # Source B: evidence/ 마지막 canonical RPU 파일 실측
    rpu_files = sorted(
        [f for f in EVIDENCE_DIR.iterdir()
         if f.name.upper().startswith("RPU-") and f.name.endswith(".json")
         and f.name not in ("RPU-ledger.json",)],
        key=lambda f: int(f.stem.split("-")[1])
    )
    if not rpu_files:
        stop("STATE_MISMATCH_PREV_HASH", "evidence/ 내 canonical RPU 없음")

    last_rpu_file = rpu_files[-1]
    last_rpu_data  = load_json(last_rpu_file)
    file_chain_hash = last_rpu_data.get("chain", {}).get("chain_hash", "")

    # 비교 1: ledger chain_tip == file chain_hash
    if ledger_chain_tip != file_chain_hash:
        stop("STATE_MISMATCH_PREV_HASH",
             f"ledger_tip={ledger_chain_tip[:16]}... "
             f"file_hash={file_chain_hash[:16]}...")

    # 비교 2: scoring_ledger.last_rpu == 실제 마지막 파일명
    expected_filename = f"{ledger_last_rpu}.json"
    actual_filename   = last_rpu_file.name
    if expected_filename.upper() != actual_filename.upper():
        stop("STATE_MISMATCH_PREV_HASH",
             f"ledger.last_rpu={ledger_last_rpu} "
             f"실제파일={actual_filename}")

    log(f"Step 2: PASS | prev_hash={ledger_chain_tip[:16]}...")
    return ledger_chain_tip

# =============================================================================
# Step 3 — Generator Call
# =============================================================================

def step3_generator(actor_id: str, content: str, prev_chain_hash: str,
                    approval_token: str, dry_run: bool,
                    event_type: str = "governance_event") -> dict:
    log("Step 3: Generator Call")

    if dry_run:
        log("Step 3: DRY-RUN — mock response 사용")
        mock = {
            "schema_version": PRODUCTION_SCHEMA,
            "rpu_id": "dry-run-mock-id",
            "timestamp": now_iso(),
            "actor_id": actor_id,
            "payload": {
                "event_type": event_type,
                "content": content
            },
            "chain": {
                "payload_hash": DRY_RUN_MOCK_PAYLOAD_HASH,
                "prev_chain_hash": prev_chain_hash,
                "chain_hash": DRY_RUN_MOCK_CHAIN_HASH
            },
            "governance_context": {}
        }
        return mock

    body = json.dumps({
        "actor_id": actor_id,
        "event_type": event_type,
        "content": content,
        "prev_chain_hash": prev_chain_hash
    }).encode("utf-8")

    req = urllib.request.Request(
        GENERATOR_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {approval_token}"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            response = json.loads(raw)
    except Exception as e:
        stop("GENERATOR_CALL_FAILED", str(e))

    # generator 응답 구조: {"status": "PASS", "candidate_rpu": {...}}
    if isinstance(response, dict) and "candidate_rpu" in response:
        if response.get("status") != "PASS":
            stop("GENERATOR_STATUS_FAIL",
                 f"status={response.get('status')}")
        if not response.get("persistence_allowed", False):
            stop("GENERATOR_PERSISTENCE_DENIED", "persistence_allowed=false")
        rpu = response["candidate_rpu"]
    else:
        rpu = response

    log(f"Step 3: PASS | rpu_id={rpu.get('rpu_id','?')}")
    return rpu


# =============================================================================
# Step 4 — Schema Gate
# =============================================================================

def step4_schema_gate(rpu: dict, prev_chain_hash: str, dry_run: bool):
    log("Step 4: Schema Gate")

    # schema_version
    if rpu.get("schema_version") != PRODUCTION_SCHEMA:
        stop("SCHEMA_GATE_FAIL",
             f"schema_version={rpu.get('schema_version')}")

    # 필수 top-level 키
    for key in ["rpu_id", "timestamp", "actor_id", "payload", "chain"]:
        if key not in rpu:
            stop("SCHEMA_GATE_FAIL", f"필수 키 누락: {key}")

    # chain 블록
    chain = rpu.get("chain", {})
    for key in ["payload_hash", "prev_chain_hash", "chain_hash"]:
        if key not in chain:
            stop("SCHEMA_GATE_FAIL", f"chain 블록 키 누락: {key}")
        if len(chain[key]) != 64:
            stop("SCHEMA_GATE_FAIL",
                 f"chain.{key} 길이 오류: {len(chain[key])}")

    # prev_chain_hash 일치 (dry-run은 mock이므로 건너뜀)
    if not dry_run:
        if chain["prev_chain_hash"] != prev_chain_hash:
            stop("SCHEMA_GATE_FAIL",
                 f"prev_chain_hash 불일치: "
                 f"expected={prev_chain_hash[:16]}... "
                 f"got={chain['prev_chain_hash'][:16]}...")

    # flat schema 흔적 검사
    forbidden = {"payload_hash", "prev_chain_hash", "chain_hash",
                 "event_type", "content"}
    leakage = set(rpu.keys()) & forbidden
    if leakage:
        stop("SCHEMA_GATE_FAIL", f"flat schema 흔적: {leakage}")

    log("Step 4: PASS")


# =============================================================================
# Step 5 — Machine PEC 생성 및 게이트
# =============================================================================

def step5_machine_pec(rpu: dict, prev_chain_hash: str,
                      event_file: str, dry_run: bool) -> dict:
    log("Step 5: Machine PEC")

    ledger = load_json(SCORING_LEDGER_PATH)
    chain  = rpu.get("chain", {})

    # candidate RPU 번호 추정
    last_rpu = ledger.get("last_rpu", "RPU-0000")
    num      = int(last_rpu.split("-")[1]) + 1
    candidate_rpu_id = f"RPU-{num:04d}"

    pec = {
        "pec_version":       "1.0",
        "issuer_version":    ISSUER_VERSION,
        "execution_time":    now_iso(),
        "dry_run":           dry_run,
        "approval_verified": True,
        "input_event_file":  event_file,
        "production_scope": {
            "chain_dir":    str(EVIDENCE_DIR),
            "ledger_ssot":  str(SCORING_LEDGER_PATH),
            "verifier_dir": "evidence/"
        },
        "pre_state": {
            "last_rpu":  last_rpu,
            "chain_tip": ledger.get("chain_tip", "")
        },
        "dual_source_prev_hash_check": {
            "ledger_chain_tip": ledger.get("chain_tip", ""),
            "file_chain_hash":  prev_chain_hash,
            "matched":          ledger.get("chain_tip") == prev_chain_hash
        },
        "generator_result": {
            "schema_version":      rpu.get("schema_version"),
            "rpu_id":              rpu.get("rpu_id"),
            "timestamp":           rpu.get("timestamp"),
            "candidate_rpu_number": candidate_rpu_id
        },
        "structure_check": {
            "top_level_keys":  list(rpu.keys()),
            "chain_keys":      list(rpu.get("chain", {}).keys()),
            "hash_lengths_ok": all(
                len(chain.get(k, "")) == 64
                for k in ["payload_hash", "prev_chain_hash", "chain_hash"]
            ),
            "nested_schema_ok": "chain" in rpu
        },
        "target_files": {
            "candidate_rpu_tmp":    str(TXN_CURRENT_DIR / f"{candidate_rpu_id}.json.tmp"),
            "candidate_ledger_tmp": str(TXN_CURRENT_DIR / "scoring_ledger.json.tmp"),
            "candidate_proof_tmp":  str(TXN_CURRENT_DIR / "latest_issue_proof.json.tmp")
        },
        "verdict": "PASS"
    }

    # verdict 최종 검증
    if not pec["dual_source_prev_hash_check"]["matched"]:
        pec["verdict"] = "FAIL"
    if not pec["structure_check"]["hash_lengths_ok"]:
        pec["verdict"] = "FAIL"
    if not pec["structure_check"]["nested_schema_ok"]:
        pec["verdict"] = "FAIL"

    if pec["verdict"] != "PASS":
        try:
            import datetime as _dt
            _fail_dir = BASE_DIR / "logs" / "pec_failures"
            _fail_dir.mkdir(parents=True, exist_ok=True)
            _ts = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            _fail_path = _fail_dir / f"PEC_FAIL_{_ts}.json"
            _log_payload = {
                "timestamp": _ts,
                "reason": "MACHINE_PEC_FAIL",
                "missing_fields": [
                    k for k in ["dual_source_prev_hash_check", "structure_check"]
                    if not pec.get(k, {}).get("matched", True)
                    or not pec.get(k, {}).get("hash_lengths_ok", True)
                    or not pec.get(k, {}).get("nested_schema_ok", True)
                ],
                "input_hash": __import__("hashlib").sha256(
                    __import__("json").dumps(pec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
                ).hexdigest()
            }
            with open(_fail_path, "w") as _f:
                __import__("json").dump(_log_payload, _f, indent=2, ensure_ascii=False)
        except Exception as _e:
            log(f"[WARN] PEC failure log write failed: {_e}")
        stop("MACHINE_PEC_FAIL", json.dumps(pec, ensure_ascii=False))

    log(f"Step 5: PASS | candidate={candidate_rpu_id}")
    return pec

# =============================================================================
# Step 6 — Transaction Snapshot
# =============================================================================

def step6_snapshot(pec: dict) -> Path:
    log("Step 6: Transaction Snapshot 생성")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_dir = TXN_CURRENT_DIR / f"txn_{ts}"
    snap_dir.mkdir(parents=True, exist_ok=True)

    # scoring_ledger.json 스냅샷
    shutil.copy2(SCORING_LEDGER_PATH, snap_dir / "scoring_ledger.json")

    # ledger.json 스냅샷
    shutil.copy2(LEDGER_PATH, snap_dir / "ledger.json")

    # 마지막 canonical RPU 스냅샷
    last_rpu_id = pec["pre_state"]["last_rpu"]
    last_rpu_path = EVIDENCE_DIR / f"{last_rpu_id}.json"
    if last_rpu_path.exists():
        shutil.copy2(last_rpu_path, snap_dir / f"{last_rpu_id}.json")

    # git HEAD commit hash
    rc, head_hash, _ = run_cmd(["git", "-C", str(BASE_DIR), "rev-parse", "HEAD"])
    rc2, git_status, _ = run_cmd(["git", "-C", str(BASE_DIR), "status", "--porcelain"])

    # proof/latest_issue_summary.json 스냅샷 (존재 시 필수)
    if PROOF_SUMMARY_PATH.exists():
        shutil.copy2(PROOF_SUMMARY_PATH, snap_dir / "latest_issue_summary.json")

    # 스냅샷 메타 저장
    snap_meta = {
        "created_at":      now_iso(),
        "snap_dir":        str(snap_dir),
        "git_head":        head_hash,
        "git_status":      git_status,
        "last_rpu":        last_rpu_id,
        "chain_tip_before": pec["pre_state"]["chain_tip"]
    }
    save_json(snap_dir / "snapshot_meta.json", snap_meta)

    log(f"Step 6: PASS | snap_dir={snap_dir.name}")
    return snap_dir


# =============================================================================
# Step 7 — Candidate Temp Write
# =============================================================================

def step7_temp_write(rpu: dict, pec: dict) -> tuple:
    """(candidate_rpu_tmp, candidate_ledger_tmp) Path 반환"""
    log("Step 7: Candidate Temp Write")

    candidate_rpu_id = pec["generator_result"]["candidate_rpu_number"]

    rpu_tmp     = TXN_CURRENT_DIR / f"{candidate_rpu_id}.json.tmp"
    ledger_tmp  = TXN_CURRENT_DIR / "scoring_ledger.json.tmp"
    ledger2_tmp = TXN_CURRENT_DIR / "ledger.json.tmp"

    save_json(rpu_tmp, rpu)
    log(f"Step 7: RPU tmp 저장 → {rpu_tmp.name}")
    return rpu_tmp, ledger_tmp, ledger2_tmp, candidate_rpu_id


# =============================================================================
# Step 8 — Candidate Ledger Rebuild
# =============================================================================

def step8_ledger_rebuild(rpu: dict, candidate_rpu_id: str,
                         ledger_tmp: Path, ledger2_tmp: Path):
    log("Step 8: Candidate Ledger Rebuild")

    new_chain_tip = rpu["chain"]["chain_hash"]

    # scoring_ledger candidate 재생성
    scoring = load_json(SCORING_LEDGER_PATH)
    scoring["chain_tip"]          = new_chain_tip
    scoring["last_rpu"]           = candidate_rpu_id
    scoring["coverage_until_rpu"] = candidate_rpu_id
    save_json(ledger_tmp, scoring)

    # ledger.json candidate 재생성
    ledger2 = load_json(LEDGER_PATH)
    ledger2["chain_tip"] = new_chain_tip
    save_json(ledger2_tmp, ledger2)

    log(f"Step 8: PASS | new_chain_tip={new_chain_tip[:16]}...")


# =============================================================================
# Step 9 — Full Verifier on Candidate (Bridge-Mode)
# =============================================================================

def step9_verify_candidate(rpu_tmp: Path, ledger_tmp: Path,
                            dry_run: bool) -> dict:
    log("Step 9: Full Verifier on Candidate (Bridge-Mode)")

    if dry_run:
        log("Step 9: DRY-RUN — verifier 건너뜀")
        return {
            "status": "PASS", "all_pass": True,
            "ledger_tip_match": True, "schema_valid": True,
            "chain_continuity": True, "checked_rpu_count": 0,
            "candidate_rpu": "dry-run-mock", "error": None
        }

    rc, out, err = run_cmd([
        "python3", str(VERIFIER_SCRIPT),
        "--candidate-rpu",    str(rpu_tmp),
        "--candidate-ledger", str(ledger_tmp),
        "--chain-dir",        str(EVIDENCE_DIR)
    ])

    try:
        result = json.loads(out)
    except Exception:
        stop("VERIFIER_OUTPUT_PARSE_FAIL", out[:300])

    if result.get("status") != "PASS":
        stop("VERIFIER_CANDIDATE_FAIL",
             json.dumps(result, ensure_ascii=False))

    if not result.get("all_pass") or not result.get("ledger_tip_match"):
        stop("VERIFIER_CANDIDATE_FAIL",
             f"all_pass={result.get('all_pass')} "
             f"ledger_tip_match={result.get('ledger_tip_match')}")

    log(f"Step 9: PASS | checked={result.get('checked_rpu_count')} RPUs")
    return result

# =============================================================================
# Step 10 — Atomic Promote (RPU → ledger → scoring_ledger 순서 고정)
# =============================================================================

def step10_atomic_promote(rpu: dict, candidate_rpu_id: str,
                          rpu_tmp: Path, ledger_tmp: Path, ledger2_tmp: Path):
    log("Step 10: Atomic Promote")

    final_rpu = EVIDENCE_DIR / f"{candidate_rpu_id}.json"
    shutil.move(str(rpu_tmp), str(final_rpu))
    log(f"Step 10: {candidate_rpu_id}.json 승격 완료")

    shutil.move(str(ledger2_tmp), str(LEDGER_PATH))
    log("Step 10: ledger.json 승격 완료")

    shutil.move(str(ledger_tmp), str(SCORING_LEDGER_PATH))
    log("Step 10: scoring_ledger.json 승격 완료 (SSOT)")

    log("Step 10: PASS")


# =============================================================================
# Step 11 — Git Commit / Push
# =============================================================================

def step11_git(candidate_rpu_id: str) -> str:
    log("Step 11: Git Commit / Push")

    files = [
        str(EVIDENCE_DIR / f"{candidate_rpu_id}.json"),
        str(SCORING_LEDGER_PATH),
        str(LEDGER_PATH),
        str(PROOF_SUMMARY_PATH),
    ]
    for f in files:
        if Path(f).exists():
            run_cmd(["git", "-C", str(BASE_DIR), "add", f])

    commit_msg = (
        f"feat: issue {candidate_rpu_id} via rpu_atomic_issuer v1.0\n\n"
        f"- schema: {PRODUCTION_SCHEMA}\n"
        f"- issuer: {ISSUER_VERSION}\n"
        f"- eag: EAG-2 approved 2026-04-09"
    )
    rc, out, err = run_cmd(["git", "-C", str(BASE_DIR), "commit", "-m", commit_msg])
    if rc != 0:
        stop("GIT_COMMIT_FAILED", err)

    rc2, out2, err2 = run_cmd(["git", "-C", str(BASE_DIR), "push"])
    if rc2 != 0:
        log(f"Step 11: git push FAILED — {err2}")
        return None

    rc3, commit_hash, _ = run_cmd(["git", "-C", str(BASE_DIR), "rev-parse", "HEAD"])
    log(f"Step 11: PASS | commit={commit_hash[:7]}")
    return commit_hash


# =============================================================================
# Step 12 — Public Proof Hook + Status Locking
# =============================================================================

def step12_proof_hook(rpu: dict, candidate_rpu_id: str,
                      verifier_result: dict, commit_hash: str,
                      push_failed: bool, snap_dir: Path):
    log("Step 12: Public Proof Hook")

    ts = now_iso()
    new_chain_tip = rpu["chain"]["chain_hash"]

    if push_failed:
        summary = {
            "issued_at":       ts,
            "last_rpu":        candidate_rpu_id,
            "public_status":   "FAILED",
            "out_of_sync":     True,
            "failure_reason":  "LOCAL_ROLLBACK_DONE_REMOTE_NOT_UPDATED"
        }
    else:
        summary = {
            "issued_at":       ts,
            "last_rpu":        candidate_rpu_id,
            "chain_tip":       new_chain_tip,
            "previous_rpu":    rpu.get("chain", {}).get("prev_chain_hash", "")[:8] + "...",
            "schema_version":  PRODUCTION_SCHEMA,
            "verifier_result": "ALL PASS",
            "git_commit":      commit_hash[:7] if commit_hash else "",
            "public_status":   "SUCCESS",
            "out_of_sync":     False
        }

    save_json(PROOF_SUMMARY_PATH, summary)

    runtime = {
        "issued_at":       ts,
        "candidate_rpu":   candidate_rpu_id,
        "push_failed":     push_failed,
        "verifier_result": verifier_result,
        "commit_hash":     commit_hash[:7] if commit_hash else None,
        "snap_dir":        str(snap_dir)
    }
    save_json(PROOF_RUNTIME_PATH, runtime)

    log(f"Step 12: PASS | public_status={summary['public_status']}")


# =============================================================================
# Step 13 — Session Delta Output
# =============================================================================

def step13_delta(rpu: dict, candidate_rpu_id: str,
                 commit_hash: str, status: str):
    log("Step 13: Session Delta Output")

    delta = {
        "status":     status,
        "last_rpu":   candidate_rpu_id,
        "chain_tip":  rpu["chain"]["chain_hash"],
        "git_commit": commit_hash[:7] if commit_hash else None,
        "proof_hook": "proof/latest_issue_summary.json"
    }
    print("\n=== SESSION DELTA ===")
    print(json.dumps(delta, ensure_ascii=False, indent=2))
    return delta


# =============================================================================
# Rollback
# =============================================================================

def rollback(snap_dir: Path, candidate_rpu_id: str,
             reason: str, commit_hash: str = None):
    log(f"ROLLBACK 시작 | reason={reason}")

    try:
        for f in TXN_CURRENT_DIR.iterdir():
            if f.name.endswith(".tmp"):
                f.unlink()
                log(f"ROLLBACK: tmp 삭제 → {f.name}")

        final_rpu = EVIDENCE_DIR / f"{candidate_rpu_id}.json"
        if final_rpu.exists():
            final_rpu.unlink()
            log(f"ROLLBACK: {candidate_rpu_id}.json 삭제")

        if snap_dir and snap_dir.exists():
            for fname in ["scoring_ledger.json", "ledger.json"]:
                snap_file = snap_dir / fname
                target    = EVIDENCE_DIR / fname
                if snap_file.exists():
                    shutil.copy2(snap_file, target)
                    log(f"ROLLBACK: {fname} 복원 완료")

        if commit_hash:
            rollback_log = {
                "timestamp":        now_iso(),
                "cancelled_commit": commit_hash[:7] if commit_hash else None,
                "reason":           reason,
                "rollback_type":    "hard",
                "status":           "COMPLETED"
            }
            log_path = TXN_HISTORY_DIR / "rollback_log.json"
            existing = []
            if log_path.exists():
                try:
                    existing = load_json(log_path)
                    if not isinstance(existing, list):
                        existing = [existing]
                except Exception:
                    existing = []
            existing.append(rollback_log)
            save_json(log_path, existing)
            log("ROLLBACK: rollback_log.json 기록 완료")

            rc, _, err = run_cmd(["git", "-C", str(BASE_DIR), "reset", "--hard", "HEAD~1"])
            if rc == 0:
                log("ROLLBACK: git reset --hard HEAD~1 완료")
            else:
                log(f"ROLLBACK: git reset 실패 — {err}")

        log("ROLLBACK: 완료")

    except Exception as e:
        log(f"ROLLBACK: 예외 발생 — {traceback.format_exc()}")


# =============================================================================
# main()
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description=ISSUER_VERSION)
    parser.add_argument("--event-file",      required=True)
    parser.add_argument("--approval-token", required=True, help="approval_token JSON 파일 경로")
    parser.add_argument("--session-count", type=int, required=True, help="SESSION_CONTEXT.session_count")
    parser.add_argument("--actor-id",        default="caddy")
    parser.add_argument("--dry-run",         action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run
    if dry_run:
        log("=== DRY-RUN MODE (Step 0~5) ===")

    event_path = Path(args.event_file)
    if not event_path.exists():
        stop("EVENT_FILE_NOT_FOUND", str(event_path))
    event = load_json(event_path)
    content = event.get("content", "")

    snap_dir         = None
    candidate_rpu_id = None
    commit_hash      = None
    rpu              = None

    try:
        step0_precondition(dry_run)
        step1_eag(args.event_file, args.approval_token, args.session_count)
        prev_hash = step2_dual_source()
        rpu       = step3_generator(args.actor_id, content,
                                     prev_hash, args.approval_token, dry_run,
                                     event_type=event.get("event_type", "governance_event"))
        step4_schema_gate(rpu, prev_hash, dry_run)
        pec = step5_machine_pec(rpu, prev_hash, args.event_file, dry_run)

        if dry_run:
            log("=== DRY-RUN COMPLETE (Step 0~5 ALL PASS) ===")
            sys.exit(0)

        snap_dir = step6_snapshot(pec)
        rpu_tmp, ledger_tmp, ledger2_tmp, candidate_rpu_id = step7_temp_write(rpu, pec)
        step8_ledger_rebuild(rpu, candidate_rpu_id, ledger_tmp, ledger2_tmp)
        verifier_result = step9_verify_candidate(rpu_tmp, ledger_tmp, dry_run)
        step10_atomic_promote(rpu, candidate_rpu_id, rpu_tmp, ledger_tmp, ledger2_tmp)

        commit_hash = step11_git(candidate_rpu_id)
        push_failed = (commit_hash is None)

        if push_failed:
            rc, head, _ = run_cmd(["git", "-C", str(BASE_DIR), "rev-parse", "HEAD"])
            rollback(snap_dir, candidate_rpu_id,
                     reason="Remote Push Failed", commit_hash=head)
            step12_proof_hook(rpu, candidate_rpu_id, verifier_result,
                              None, push_failed=True, snap_dir=snap_dir)
            step13_delta(rpu, candidate_rpu_id, None, "FAILED")
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fail_dir = FAILED_DIR / ts
            fail_dir.mkdir(parents=True, exist_ok=True)
            save_json(fail_dir / "machine_pec.json", pec)
            save_json(fail_dir / "error.json",
                      {"reason": "GIT_PUSH_FAILED", "timestamp": now_iso()})
            sys.exit(1)

        step12_proof_hook(rpu, candidate_rpu_id, verifier_result,
                          commit_hash, push_failed=False, snap_dir=snap_dir)
        step13_delta(rpu, candidate_rpu_id, commit_hash, "SUCCESS")

        shutil.rmtree(str(TXN_CURRENT_DIR), ignore_errors=True)
        TXN_CURRENT_DIR.mkdir(parents=True, exist_ok=True)
        log("=== RPU ATOMIC ISSUER: SUCCESS ===")

    except SystemExit:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fail_dir = FAILED_DIR / ts
        fail_dir.mkdir(parents=True, exist_ok=True)
        if rpu:
            save_json(fail_dir / "generator_output.json", rpu)
        save_json(fail_dir / "error.json",
                  {"reason": "STOP_CALLED", "timestamp": now_iso()})
        if snap_dir and candidate_rpu_id:
            rollback(snap_dir, candidate_rpu_id, reason="STOP_CALLED")
        raise

    except Exception:
        log(f"UNHANDLED EXCEPTION: {traceback.format_exc()}")
        if snap_dir and candidate_rpu_id:
            rollback(snap_dir, candidate_rpu_id, reason="UNHANDLED_EXCEPTION")
        sys.exit(1)


if __name__ == "__main__":
    main()
