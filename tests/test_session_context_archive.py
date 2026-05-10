"""
test_session_context_archive.py
PT-S99-GOV-003 Rev.3 FINAL — Tier D migration executor 검증

TC-1:  COMPLETED 항목 정상 archive 이관
TC-2:  CANCELED 항목 정상 archive 이관
TC-3:  SUPERSEDED 항목 정상 archive 이관
TC-4:  T2 WARN active 항목 archive 이동 금지 (hard-lock)
TC-5:  Tier A LOCKED key archive 이동 시도 거부
TC-6:  archive item 필수 필드 전항목 존재 확인
TC-7:  T2 WARN active 아닌 IN_PROGRESS 항목 잔류 확인
TC-8:  dry_run=True 시 session_context 변경 없음 확인
TC-9:  Complexity Ceiling SYSTEM_REVIEW_REQUIRED 판정
TC-10: Complexity Ceiling HARD_STOP 판정
TC-11: archive 파일 부재 시 FAIL 반환
TC-12: SESSION_CONTEXT_ARCHIVE.json hidden graveyard 아님 확인
         (source_key / source_path / payload_hash_sha256 필수 조건)
"""

import json
import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock

# sys.path 주입 (importlib 모드 대응)
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "session_context_gen"))

from session_context_archive import (
    run_tier_d_migration,
    _build_archive_item,
    _check_complexity_ceiling,
    _evaluate_tier_d_eligibility,
    ArchiveError,
    ArchiveItemInvalidError,
    T2WarnActiveError,
    TierAViolationError,
    REQUIRED_ARCHIVE_FIELDS,
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


def _make_context_with(active_tasks=None, archived_tasks=None, extra_keys=0) -> dict:
    ctx = {
        "session_count": 113,
        "architecture": "AIBA Session Sync Architecture v1.0",
        "active_tasks": active_tasks or [],
        "archived_tasks": archived_tasks or [],
    }
    for i in range(extra_keys):
        ctx[f"extra_key_{i}"] = f"value_{i}"
    return ctx


# ── TC-1: COMPLETED 항목 정상 이관 ───────────────────────────────────────────

def test_tc1_completed_migrated(tmp_path):
    archive_path = _make_archive(tmp_path)
    ctx = _make_context_with(active_tasks=[
        {"id": "PT-001", "status": "COMPLETED", "task": "done task"}
    ])
    result = run_tier_d_migration(ctx, session=113, archive_path=archive_path)
    assert result["status"] == "SUCCESS", result["errors"]
    assert result["migrated_count"] == 1
    assert result["remaining_count"] == 0
    # archive 파일에 저장됐는지 확인
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["total_items"] == 1
    assert archive["items"][0]["source_key"] == "active_tasks"


# ── TC-2: CANCELED 항목 정상 이관 ────────────────────────────────────────────

def test_tc2_canceled_migrated(tmp_path):
    archive_path = _make_archive(tmp_path)
    ctx = _make_context_with(active_tasks=[
        {"id": "PT-002", "status": "CANCELED", "task": "canceled task"}
    ])
    result = run_tier_d_migration(ctx, session=113, archive_path=archive_path)
    assert result["status"] == "SUCCESS", result["errors"]
    assert result["migrated_count"] == 1


# ── TC-3: SUPERSEDED 항목 정상 이관 ──────────────────────────────────────────

def test_tc3_superseded_migrated(tmp_path):
    archive_path = _make_archive(tmp_path)
    ctx = _make_context_with(archived_tasks=[
        {"id": "PT-003", "status": "SUPERSEDED", "task": "superseded task"}
    ])
    result = run_tier_d_migration(ctx, session=113, archive_path=archive_path)
    assert result["status"] == "SUCCESS", result["errors"]
    assert result["migrated_count"] == 1


# ── TC-4: T2 WARN active 항목 archive 이동 금지 (hard-lock) ──────────────────

def test_tc4_t2_warn_hard_lock(tmp_path):
    archive_path = _make_archive(tmp_path)
    ctx = _make_context_with(active_tasks=[
        {"id": "PT-T2-WARN", "status": "COMPLETED", "task": "t2 warn item"}
    ])
    result = run_tier_d_migration(
        ctx, session=113, archive_path=archive_path,
        t2_warn_active_ids={"PT-T2-WARN"}
    )
    assert result["status"] == "FAIL"
    assert any("T2 WARN" in e for e in result["errors"])
    # archive 파일 변경 없음 확인
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["total_items"] == 0


# ── TC-5: Tier A LOCKED key 거부 ──────────────────────────────────────────────

def test_tc5_tier_a_locked_key_rejected():
    with pytest.raises(TierAViolationError):
        _evaluate_tier_d_eligibility(
            key="session_count",
            items=[{"id": "x", "status": "COMPLETED"}],
            t2_warn_active_ids=set(),
        )


# ── TC-6: archive item 필수 필드 전항목 존재 확인 ──────────────────────────────

def test_tc6_required_fields_present(tmp_path):
    archive_path = _make_archive(tmp_path)
    ctx = _make_context_with(active_tasks=[
        {"id": "PT-006", "status": "COMPLETED", "task": "field check"}
    ])
    run_tier_d_migration(ctx, session=113, archive_path=archive_path)
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    item = archive["items"][0]
    for field in REQUIRED_ARCHIVE_FIELDS:
        assert field in item, f"필수 필드 누락: {field}"
        assert item[field], f"필수 필드 빈 값: {field}"


# ── TC-7: IN_PROGRESS 항목 잔류 확인 ──────────────────────────────────────────

def test_tc7_in_progress_remains(tmp_path):
    archive_path = _make_archive(tmp_path)
    ctx = _make_context_with(active_tasks=[
        {"id": "PT-007a", "status": "COMPLETED", "task": "done"},
        {"id": "PT-007b", "status": "IN_PROGRESS", "task": "ongoing"},
    ])
    result = run_tier_d_migration(ctx, session=113, archive_path=archive_path)
    assert result["status"] == "SUCCESS", result["errors"]
    assert result["migrated_count"] == 1
    assert result["remaining_count"] == 1
    # session_context 내 잔류 확인
    assert len(ctx["active_tasks"]) == 1
    assert ctx["active_tasks"][0]["id"] == "PT-007b"


# ── TC-8: dry_run=True 시 변경 없음 확인 ──────────────────────────────────────

def test_tc8_dry_run_no_mutation(tmp_path):
    archive_path = _make_archive(tmp_path)
    ctx = _make_context_with(active_tasks=[
        {"id": "PT-008", "status": "COMPLETED", "task": "dry run item"}
    ])
    original_count = len(ctx["active_tasks"])
    result = run_tier_d_migration(ctx, session=113, archive_path=archive_path, dry_run=True)
    assert result["status"] == "SUCCESS", result["errors"]
    # session_context 변경 없음
    assert len(ctx["active_tasks"]) == original_count
    # archive 파일 변경 없음
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["total_items"] == 0


# ── TC-9: Complexity Ceiling SYSTEM_REVIEW_REQUIRED ──────────────────────────

def test_tc9_ceiling_system_review_required():
    ctx = {f"key_{i}": f"val_{i}" for i in range(41)}
    result = _check_complexity_ceiling(ctx)
    assert result["status"] == "SYSTEM_REVIEW_REQUIRED"
    assert result["key_count"] == 41


# ── TC-10: Complexity Ceiling HARD_STOP ──────────────────────────────────────

def test_tc10_ceiling_hard_stop(tmp_path):
    archive_path = _make_archive(tmp_path)
    # 43개 top-level key 생성
    ctx = {f"key_{i}": f"val_{i}" for i in range(43)}
    ctx["active_tasks"] = []
    ctx["archived_tasks"] = []
    result = run_tier_d_migration(ctx, session=113, archive_path=archive_path)
    assert result["status"] == "FAIL"
    assert result["ceiling_check"]["status"] == "HARD_STOP"


# ── TC-11: archive 파일 부재 시 FAIL ─────────────────────────────────────────

def test_tc11_archive_missing(tmp_path):
    missing_path = tmp_path / "NO_SUCH_ARCHIVE.json"
    ctx = _make_context_with()
    result = run_tier_d_migration(ctx, session=113, archive_path=missing_path)
    assert result["status"] == "FAIL"
    assert any("not found" in e for e in result["errors"])


# ── TC-12: recoverable reference layer 확인 ───────────────────────────────────

def test_tc12_recoverable_reference_layer(tmp_path):
    """
    T-3 검증: SESSION_CONTEXT_ARCHIVE.json이
    hidden graveyard가 아닌 recoverable reference layer인가
    (source_key / source_path / payload_hash_sha256 필수 조건)
    """
    archive_path = _make_archive(tmp_path)
    ctx = _make_context_with(active_tasks=[
        {"id": "PT-012", "status": "COMPLETED", "task": "recover me"}
    ])
    run_tier_d_migration(ctx, session=113, archive_path=archive_path)
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    item = archive["items"][0]

    # 복구에 필요한 핵심 3요소 확인
    assert item["source_key"], "source_key 없음 — 복구 불가"
    assert item["source_path"], "source_path 없음 — 복구 불가"
    assert item["payload_hash_sha256"], "payload_hash_sha256 없음 — 무결성 확인 불가"
    # original_payload 보존 확인
    assert "original_payload" in item
    assert item["original_payload"]["id"] == "PT-012"
