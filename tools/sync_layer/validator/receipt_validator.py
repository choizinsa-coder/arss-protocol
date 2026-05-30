"""
receipt_validator.py
AIBA Sync Layer — Deployment Receipt Validator (P3-T5)
SSOT: Domi Phase 3 Design (S171) / EAG-1 Approved (비오(Joshua))

역할:
  - registry/deployment_receipts/*.json 검증
  - R1: DEPLOYMENT_RECEIPT_v1 11개 필수 필드 존재 (p3_receipt_schema 권위)
  - R2: receipt_version == "DEPLOYMENT_RECEIPT_v1"
  - R3: artifact_hash 존재 + 유효 SHA256 hex (64자)
판정: PASS / FAIL / UNKNOWN (fail-closed)

금지:
  - 수정 / 복구 / 재배포
  - UNKNOWN → PASS 승격
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
RECEIPT_DIR = VPS_ROOT / "registry" / "deployment_receipts"
RECEIPT_VERSION = "DEPLOYMENT_RECEIPT_v1"

# p3_receipt_schema.tier1_fields (SESSION_CONTEXT 권위, SC-2 해소)
TIER1_REQUIRED_FIELDS = frozenset({
    "deployment_id",
    "deploy_type",
    "actor",
    "approval_id",
    "artifact_hash",
    "target",
    "result",
    "timestamp",
    "request_id",
    "session",
    "receipt_version",
})

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_UNKNOWN = "UNKNOWN"


def validate() -> dict:
    """
    Deployment Receipt 전체 검증 진입점.
    registry/deployment_receipts/*.json 전수 검사.
    반환: {validator, verdict, checked, failed, details[]}
    CC=4
    """
    if not RECEIPT_DIR.exists():
        return _result(VERDICT_UNKNOWN, 0, 0, [{"error": "RECEIPT_DIR_NOT_FOUND"}])

    try:
        receipt_files = sorted(RECEIPT_DIR.glob("*.json"))
    except OSError as exc:
        return _result(VERDICT_UNKNOWN, 0, 0, [{"error": f"DIR_SCAN_FAILED: {exc}"}])

    if not receipt_files:
        return _result(VERDICT_UNKNOWN, 0, 0, [{"note": "NO_RECEIPTS_FOUND"}])

    checked = 0
    failed = 0
    details = []

    for rfile in receipt_files:
        checked += 1
        verdict, issues = _validate_single(rfile)
        if verdict != VERDICT_PASS:
            failed += 1
            details.append({"file": rfile.name, "verdict": verdict, "issues": issues})

    overall = VERDICT_PASS if failed == 0 else VERDICT_FAIL
    return _result(overall, checked, failed, details)


def _validate_single(path: Path) -> tuple:
    """
    단일 receipt 파일 검증.
    반환: (verdict, issues[])
    CC=5
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return VERDICT_UNKNOWN, [f"PARSE_FAILED: {exc}"]

    issues = []

    # R1: 필수 필드 11개 존재
    missing = TIER1_REQUIRED_FIELDS - set(data.keys())
    if missing:
        issues.append(f"R1_MISSING_FIELDS: {sorted(missing)}")

    # R2: schema version 확인
    if data.get("receipt_version") != RECEIPT_VERSION:
        issues.append(f"R2_VERSION_MISMATCH: {data.get('receipt_version')!r}")

    # R3: artifact_hash 유효 SHA256 hex
    artifact_hash = data.get("artifact_hash", "")
    if not _is_valid_sha256_hex(artifact_hash):
        issues.append(f"R3_INVALID_ARTIFACT_HASH: {str(artifact_hash)[:16]!r}")

    if issues:
        return VERDICT_FAIL, issues
    return VERDICT_PASS, []


def _is_valid_sha256_hex(value: str) -> bool:
    """
    SHA256 hex string 유효성 확인 (64자 lowercase hex).
    CC=3
    """
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def _result(verdict: str, checked: int, failed: int, details: list) -> dict:
    """결과 딕셔너리 빌드. CC=1"""
    return {
        "validator": "receipt",
        "verdict": verdict,
        "checked": checked,
        "failed": failed,
        "details": details,
    }


def get_validator_status() -> dict:
    """Receipt Validator 상태 요약 (관측/감사용). CC=1"""
    count = len(list(RECEIPT_DIR.glob("*.json"))) if RECEIPT_DIR.exists() else 0
    return {
        "component": "receipt_validator",
        "layer": "sync_layer/validator",
        "p3_task": "P3-T5",
        "receipt_dir": str(RECEIPT_DIR),
        "receipt_count": count,
        "required_fields_count": len(TIER1_REQUIRED_FIELDS),
        "required_fields": sorted(TIER1_REQUIRED_FIELDS),
        "schema_authority": "p3_receipt_schema.tier1_fields (SESSION_CONTEXT)",
    }
