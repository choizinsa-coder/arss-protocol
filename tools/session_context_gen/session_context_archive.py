ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"

"""
session_context_archive.py
PT-S99-GOV-003 Rev.3 FINAL — SESSION_CONTEXT Growth Governance
Tier D migration executor (canonical inflation containment)

REV-D: 호출 위치 — stage 5_normalize_state_events 완료 이후,
       stage 13_generate_receipt (SESSION_CONTEXT.json 생성) 이전 mandatory.

설계 원칙:
  - 목표: explicit canonical reduction + recoverable archive
  - 금지: T2 WARN concealment / stale hiding / semantic interpretation
  - 필수: archive item 전항목 필드 존재 (archive_id/source_key/source_path/
          migration_rule/payload_hash_sha256)
  - T2 WARN active 항목 archive 이동 금지 (hard-lock)
  - closed-set event_type retention mandatory
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ARCHIVE_PATH = Path("/opt/arss/engine/arss-protocol/SESSION_CONTEXT_ARCHIVE.json")

# EAG-3 성공 기준 §12: archive item 필수 필드
REQUIRED_ARCHIVE_FIELDS = [
    "archive_id",
    "source_key",
    "source_path",
    "migration_rule",
    "payload_hash_sha256",
]

# Tier D 이관 대상 status 값 (REV-C: CLOSED/CANCELED/SUPERSEDED 직접 archive)
TIER_D_ELIGIBLE_STATUSES = {"CLOSED", "CANCELED", "SUPERSEDED", "COMPLETED"}

# Tier A LOCKED 집합 — 절대 archive 이동 금지
TIER_A_LOCKED_KEYS = {
    "activation_allowed",
    "architecture",
    "session_count",
    "session_delta",
    "session_open_rules",
    "session_close_rules",
    "session_reentry",
    "chain",
    "ssoi_status",
    "canonical_rules",
    "lessons",
}

# T2 WARN 판단 기준 필드 (stale_state_detector 연동)
T2_WARN_INDICATOR_KEY = "_t2_warn_active"


class ArchiveError(Exception):
    pass


class T2WarnActiveError(ArchiveError):
    """T2 WARN active 항목 archive 이동 시도 — hard-lock 발동"""
    pass


class TierAViolationError(ArchiveError):
    """Tier A LOCKED 항목 archive 이동 시도 — 즉시 거부"""
    pass


class ArchiveItemInvalidError(ArchiveError):
    """archive item 필수 필드 누락 — 복구 가능 항목 불인정"""
    pass


def _utc_ts() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


def _sha256(data: Any) -> str:
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_archive(archive_path: Path) -> dict:
    if not archive_path.exists():
        raise ArchiveError(f"SESSION_CONTEXT_ARCHIVE.json not found: {archive_path}")
    with open(archive_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_archive(archive_data: dict, archive_path: Path) -> None:
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, ensure_ascii=False, indent=2)


def _check_t2_warn(item: dict, t2_warn_active_ids: set) -> bool:
    """T2 WARN active 여부 확인. active 시 True 반환."""
    item_id = item.get("id", "")
    if item_id and item_id in t2_warn_active_ids:
        return True
    if item.get(T2_WARN_INDICATOR_KEY, False):
        return True
    return False


def _build_archive_item(
    source_key: str,
    source_path: str,
    item: dict,
    migration_rule: str,
    session: int,
) -> dict:
    """
    archive item 구성. 필수 필드 전항목 포함.
    EAG-3 성공 기준 §12: 하나라도 누락 시 복구 가능 항목 불인정.
    """
    payload_hash = _sha256(item)
    archive_id = f"ARCH-{source_key}-{session}-{payload_hash[:8]}"

    archive_item = {
        "archive_id": archive_id,
        "source_key": source_key,
        "source_path": source_path,
        "migration_rule": migration_rule,
        "payload_hash_sha256": payload_hash,
        "migrated_session": session,
        "migrated_at": _utc_ts(),
        "original_payload": item,
    }

    # 필수 필드 검증
    missing = [f for f in REQUIRED_ARCHIVE_FIELDS if not archive_item.get(f)]
    if missing:
        raise ArchiveItemInvalidError(
            f"archive item 필수 필드 누락: {missing} — 복구 가능 항목 불인정"
        )

    return archive_item


def _evaluate_tier_d_eligibility(
    key: str,
    items: list,
    t2_warn_active_ids: set,
) -> tuple[list, list]:
    """
    Tier D eligibility 평가.
    반환: (eligible_items, ineligible_items)

    금지 조건:
      - Tier A LOCKED key
      - T2 WARN active 항목
      - TIER_D_ELIGIBLE_STATUSES에 해당하지 않는 status
    """
    if key in TIER_A_LOCKED_KEYS:
        raise TierAViolationError(
            f"Tier A LOCKED key archive 이동 시도 금지: {key}"
        )

    eligible = []
    ineligible = []

    for item in items:
        status = item.get("status", "")

        # T2 WARN hard-lock
        if _check_t2_warn(item, t2_warn_active_ids):
            raise T2WarnActiveError(
                f"T2 WARN active 항목 archive 이동 금지 (hard-lock): id={item.get('id', '?')}"
            )

        if status in TIER_D_ELIGIBLE_STATUSES:
            eligible.append(item)
        else:
            ineligible.append(item)

    return eligible, ineligible


def _check_complexity_ceiling(session_context: dict) -> dict:
    """
    Complexity Ceiling 평가.
    41~42개: SYSTEM REVIEW REQUIRED (즉시 FAIL 아님)
    43개 이상: HARD STOP
    """
    top_level_keys = len(session_context.keys())
    result = {
        "key_count": top_level_keys,
        "ceiling_limit": 42,
        "status": "OK",
        "action_required": None,
    }

    if top_level_keys > 42:
        result["status"] = "HARD_STOP"
        result["action_required"] = f"top-level key {top_level_keys}개 — Ceiling 초과. 즉시 중단 필요."
    elif top_level_keys >= 41:
        result["status"] = "SYSTEM_REVIEW_REQUIRED"
        result["action_required"] = f"top-level key {top_level_keys}개 — Ceiling 임박. SYSTEM REVIEW REQUIRED."

    return result


def _collect_migration_candidates(
    session_context: dict,
    t2_warn_active_ids: set,
    session: int,
) -> tuple:
    """
    Step 3~4: eligibility 평가 + archive_item 생성.
    반환: (migrated_items, ineligibles_by_key, errors)
    errors 비어있으면 성공, 있으면 FAIL.
    ineligibles_by_key: {source_key: [ineligible_items]}
    """
    keys_to_process = ["active_tasks", "archived_tasks"]
    migrated_items = []
    ineligibles_by_key = {}
    errors = []

    for source_key in keys_to_process:
        items = session_context.get(source_key, [])
        if not items:
            ineligibles_by_key[source_key] = []
            continue

        # Step 3: eligibility 평가
        try:
            eligible, ineligible = _evaluate_tier_d_eligibility(
                source_key, items, t2_warn_active_ids
            )
        except (TierAViolationError, T2WarnActiveError) as e:
            errors.append(str(e))
            return migrated_items, ineligibles_by_key, errors

        # Step 4: hash snapshot + archive_item 생성
        for item in eligible:
            try:
                archive_item = _build_archive_item(
                    source_key=source_key,
                    source_path=f"session_context.{source_key}",
                    item=item,
                    migration_rule="TIER_D_AUTO_MIGRATION_REV3",
                    session=session,
                )
                migrated_items.append((source_key, item, archive_item))
            except ArchiveItemInvalidError as e:
                errors.append(str(e))
                return migrated_items, ineligibles_by_key, errors

        ineligibles_by_key[source_key] = ineligible

    return migrated_items, ineligibles_by_key, errors


def _execute_tier_d_transfer(
    migrated_items: list,
    ineligibles_by_key: dict,
    session_context: dict,
    archive_data: dict,
    archive_path: Path,
    session: int,
    dry_run: bool,
) -> tuple:
    """
    Step 5~6: Tier D residue 제거 + archive 저장.
    반환: (remaining_count, r3_receipt_required, error_str | None)
    """
    remaining_count = 0

    # Step 5: Tier D residue 제거 (ineligible 직접 적용)
    for source_key, ineligible in ineligibles_by_key.items():
        items = session_context.get(source_key, [])
        if not items:
            continue
        if not dry_run:
            session_context[source_key] = ineligible
            remaining_count += len(ineligible)
        else:
            remaining_count += len(items)

    # Step 6: archive 저장
    r3_receipt_required = False
    if migrated_items and not dry_run:
        if "items" not in archive_data:
            archive_data["items"] = []
        for _, _, archive_item in migrated_items:
            archive_data["items"].append(archive_item)
        archive_data["last_migration_session"] = session
        archive_data["last_migration_at"] = _utc_ts()
        archive_data["total_items"] = len(archive_data["items"])
        r3_receipt_required = True

        try:
            _save_archive(archive_data, archive_path)
        except Exception as e:
            return remaining_count, r3_receipt_required, f"archive 저장 실패: {e}"

    return remaining_count, r3_receipt_required, None


def run_tier_d_migration(
    session_context: dict,
    session: int,
    archive_path: Path = ARCHIVE_PATH,
    t2_warn_active_ids: Optional[set] = None,
    dry_run: bool = False,
) -> dict:
    """
    Tier D migration 실행기.

    REV-D 호출 위치: stage 5_normalize_state_events 완료 이후,
                    stage 13_generate_receipt 이전.

    반환값:
      {
        "status": "SUCCESS" | "SKIPPED" | "FAIL",
        "migrated_count": int,
        "remaining_count": int,
        "ceiling_check": dict,
        "r3_receipt_required": bool,
        "detail": str,
        "errors": list,
      }
    """
    if t2_warn_active_ids is None:
        t2_warn_active_ids = set()

    result = {
        "status": "SUCCESS",
        "migrated_count": 0,
        "remaining_count": 0,
        "ceiling_check": {},
        "r3_receipt_required": False,
        "detail": "",
        "errors": [],
    }

    # Step 2: archive 로드
    try:
        archive_data = _load_archive(archive_path)
    except ArchiveError as e:
        result["status"] = "FAIL"
        result["errors"].append(str(e))
        return result

    # Step 3~4: 이관 대상 수집
    migrated_items, ineligibles_by_key, errors = _collect_migration_candidates(
        session_context, t2_warn_active_ids, session
    )
    if errors:
        result["status"] = "FAIL"
        result["errors"].extend(errors)
        return result

    # Step 5~6: 실제 이관 실행
    remaining_count, r3_required, transfer_error = _execute_tier_d_transfer(
        migrated_items, ineligibles_by_key, session_context, archive_data, archive_path, session, dry_run
    )
    if transfer_error:
        result["status"] = "FAIL"
        result["errors"].append(transfer_error)
        return result

    result["migrated_count"] = len(migrated_items)
    result["remaining_count"] = remaining_count
    result["r3_receipt_required"] = r3_required

    # Step 7: Complexity Ceiling 평가
    ceiling = _check_complexity_ceiling(session_context)
    result["ceiling_check"] = ceiling

    if ceiling["status"] == "HARD_STOP":
        result["status"] = "FAIL"
        result["errors"].append(ceiling["action_required"])
        return result

    result["detail"] = (
        f"migrated={result['migrated_count']}, "
        f"remaining={result['remaining_count']}, "
        f"ceiling={ceiling['status']}({ceiling['key_count']}keys)"
    )

    return result
