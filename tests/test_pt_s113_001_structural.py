"""
test_pt_s113_001_structural.py
PT-S113-TEST-001 Layer-1 — Snapshot Structural Test
PT-S99-GOV-003 Rev.3 FINAL growth-governance 구조 검증

고정 fixture 기반. production 코드/live SESSION_CONTEXT 변화에 무관하게 안정적.
검증 대상: schema integrity / migration rule / archive structure /
           Tier semantics / receipt structure
"""

import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "session_context_gen"))

from session_context_archive import (
    run_tier_d_migration,
    _build_archive_item,
    _check_complexity_ceiling,
    REQUIRED_ARCHIVE_FIELDS,
    TIER_A_LOCKED_KEYS,
    TIER_D_ELIGIBLE_STATUSES,
    T2WarnActiveError,
    TierAViolationError,
    ArchiveItemInvalidError,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_archive(tmp_path: Path) -> Path:
    archive_path = tmp_path / "SESSION_CONTEXT_ARCHIVE.json"
    archive_data = {
        "schema_version": "1.0.0",
        "spec_id": "PT-S99-GOV-003-REV3-FINAL",
        "total_items": 0,
        "last_migration_session": None,
        "last_migration_at": None,
        "items": [],
    }
    archive_path.write_text(json.dumps(archive_data), encoding="utf-8")
    return archive_path


# ── S-1: REQUIRED_ARCHIVE_FIELDS 스키마 계약 ──────────────────────────────────

def test_s1_required_archive_fields_schema():
    """archive item 필수 필드 5종 계약 확인 — EAG-3 성공 기준 §12"""
    expected = {
        "archive_id", "source_key", "source_path",
        "migration_rule", "payload_hash_sha256"
    }
    assert set(REQUIRED_ARCHIVE_FIELDS) == expected


# ── S-2: Tier A LOCKED 집합 불변성 ────────────────────────────────────────────

def test_s2_tier_a_locked_keys_invariant():
    """Tier A LOCKED 집합이 canonical key를 포함하는지 확인"""
    must_include = {
        "activation_allowed", "session_count", "chain",
        "canonical_rules", "lessons", "session_open_rules",
        "session_close_rules",
    }
    assert must_include.issubset(TIER_A_LOCKED_KEYS)


# ── S-3: Tier D eligible status closed-set ────────────────────────────────────

def test_s3_tier_d_eligible_statuses_closed_set():
    """Tier D 이관 대상 status closed-set 확인"""
    expected = {"CLOSED", "CANCELED", "SUPERSEDED", "COMPLETED"}
    assert TIER_D_ELIGIBLE_STATUSES == expected


# ── S-4: archive item 구조 무결성 ─────────────────────────────────────────────

def test_s4_archive_item_structure():
    """_build_archive_item 반환 구조 — 필수 필드 전항목 존재"""
    item = {"id": "PT-S4", "status": "COMPLETED", "task": "structural test"}
    archive_item = _build_archive_item(
        source_key="active_tasks",
        source_path="session_context.active_tasks",
        item=item,
        migration_rule="TIER_D_AUTO_MIGRATION_REV3",
        session=113,
    )
    for field in REQUIRED_ARCHIVE_FIELDS:
        assert field in archive_item, f"필수 필드 누락: {field}"
        assert archive_item[field], f"필수 필드 빈 값: {field}"
    assert "original_payload" in archive_item
    assert archive_item["original_payload"] == item


# ── S-5: archive item recoverable reference 3요소 ─────────────────────────────

def test_s5_recoverable_reference_three_elements():
    """T-3 검증: source_key / source_path / payload_hash_sha256 필수 존재"""
    item = {"id": "PT-S5", "status": "CANCELED", "task": "recover check"}
    archive_item = _build_archive_item(
        source_key="active_tasks",
        source_path="session_context.active_tasks",
        item=item,
        migration_rule="TIER_D_AUTO_MIGRATION_REV3",
        session=113,
    )
    assert archive_item["source_key"] == "active_tasks"
    assert archive_item["source_path"] == "session_context.active_tasks"
    assert len(archive_item["payload_hash_sha256"]) == 64  # SHA256 hex


# ── S-6: Complexity Ceiling semantics ─────────────────────────────────────────

def test_s6_ceiling_ok():
    ctx = {f"k_{i}": i for i in range(30)}
    result = _check_complexity_ceiling(ctx)
    assert result["status"] == "OK"
    assert result["ceiling_limit"] == 42


def test_s6_ceiling_review_required():
    ctx = {f"k_{i}": i for i in range(41)}
    result = _check_complexity_ceiling(ctx)
    assert result["status"] == "SYSTEM_REVIEW_REQUIRED"


def test_s6_ceiling_hard_stop():
    ctx = {f"k_{i}": i for i in range(43)}
    result = _check_complexity_ceiling(ctx)
    assert result["status"] == "HARD_STOP"


# ── S-7: T2 WARN hard-lock 구조 ───────────────────────────────────────────────

def test_s7_t2_warn_hard_lock_structure(tmp_path):
    """T2 WARN active 항목 archive 이동 시 FAIL 반환 — 구조적 차단"""
    archive_path = _make_archive(tmp_path)
    ctx = {
        "active_tasks": [{"id": "PT-T2", "status": "COMPLETED", "task": "t2 item"}],
        "archived_tasks": [],
    }
    result = run_tier_d_migration(
        ctx, session=113, archive_path=archive_path,
        t2_warn_active_ids={"PT-T2"}
    )
    assert result["status"] == "FAIL"
    assert any("T2 WARN" in e for e in result["errors"])
    # archive 변경 없음
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["total_items"] == 0


# ── S-8: Tier A 확장 금지 구조 ────────────────────────────────────────────────

def test_s8_tier_a_expansion_forbidden():
    """Tier A key에 대한 archive 이동 시도 시 TierAViolationError 발생"""
    with pytest.raises(TierAViolationError):
        from session_context_archive import _evaluate_tier_d_eligibility
        _evaluate_tier_d_eligibility(
            key="canonical_rules",
            items=[{"id": "x", "status": "COMPLETED"}],
            t2_warn_active_ids=set(),
        )


# ── S-9: dry_run 구조적 격리 ──────────────────────────────────────────────────

def test_s9_dry_run_structural_isolation(tmp_path):
    """dry_run=True 시 session_context 및 archive 파일 변경 없음"""
    archive_path = _make_archive(tmp_path)
    ctx = {
        "active_tasks": [{"id": "PT-S9", "status": "COMPLETED", "task": "dry"}],
        "archived_tasks": [],
    }
    original_len = len(ctx["active_tasks"])
    result = run_tier_d_migration(
        ctx, session=113, archive_path=archive_path, dry_run=True
    )
    assert result["status"] == "SUCCESS"
    assert len(ctx["active_tasks"]) == original_len
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["total_items"] == 0


# ── S-10: REV-D migration_rule 계약 ──────────────────────────────────────────

def test_s10_migration_rule_contract():
    """archive item migration_rule 값이 REV-D 계약값과 일치"""
    item = {"id": "PT-S10", "status": "SUPERSEDED", "task": "rule check"}
    archive_item = _build_archive_item(
        source_key="archived_tasks",
        source_path="session_context.archived_tasks",
        item=item,
        migration_rule="TIER_D_AUTO_MIGRATION_REV3",
        session=113,
    )
    assert archive_item["migration_rule"] == "TIER_D_AUTO_MIGRATION_REV3"
