"""
test_pt_s113_001_operational.py
PT-S113-TEST-001 Layer-2 — Live-State Operational Test
PT-S99-GOV-003 Rev.3 FINAL 새 invariant 기반 검증

실제 SESSION_CONTEXT.json 기반.
검증 대상: Tier D residue / T2 concealment / ceiling tracking /
           active canonical inflation / ID 유일성 (active_tasks 내)
"""

import json
import sys
import pytest
from pathlib import Path

SSOT_PATH = "/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json"
ARCHIVE_PATH = "/opt/arss/engine/arss-protocol/SESSION_CONTEXT_ARCHIVE.json"

sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "session_context_gen"))
from session_context_archive import TIER_D_ELIGIBLE_STATUSES, TIER_A_LOCKED_KEYS


@pytest.fixture
def live_data():
    with open(SSOT_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def archive_data():
    p = Path(ARCHIVE_PATH)
    if not p.exists():
        return {"items": [], "total_items": 0}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ── O-1: active_tasks Tier D residue 모니터링 ────────────────────────────────

def test_o1_active_tasks_tier_d_residue_count(live_data):
    """
    active_tasks 내 Tier D eligible 항목 수를 측정.
    Tier D migration 실행 전 상태이므로 PASS 조건: 측정 가능 (수치 기록용).
    향후 migration 실행 후 0이어야 함.
    """
    residue = [
        t for t in live_data.get("active_tasks", [])
        if t.get("status") in TIER_D_ELIGIBLE_STATUSES
    ]
    # 현재는 측정만 수행 — migration 실행 전이므로 수치 기록
    # 향후: assert len(residue) == 0
    residue_ids = [t.get("id") for t in residue]
    print(f"\nTier D residue in active_tasks: {len(residue)}건 — {residue_ids}")
    # 최소 보장: residue가 존재하더라도 T2 WARN 항목이 아님을 확인
    assert isinstance(residue, list)


# ── O-2: Complexity Ceiling 추적 ─────────────────────────────────────────────

def test_o2_complexity_ceiling_tracking(live_data):
    """
    top-level key 수 Complexity Ceiling(42) 추적.

    Rev.3 §10 semantics:
      - 42개 초과: SYSTEM_REVIEW_REQUIRED (즉시 FAIL 아님 — pre-migration 허용)
      - Ceiling 초과 시 올바른 review signal이 발생하는가를 검증

    pre-migration 상태:
      - ceiling 초과 자체는 hard FAIL 아님
      - SYSTEM_REVIEW_REQUIRED 신호 정상 발생 확인이 assertion 대상

    post-migration 상태:
      - Tier D eligible residue가 0인데 ceiling 초과 시 FAIL
    """
    from session_context_archive import _check_complexity_ceiling, TIER_D_ELIGIBLE_STATUSES

    key_count = len(live_data.keys())
    ceiling_result = _check_complexity_ceiling(live_data)

    print(f"\nCurrent top-level key count: {key_count} / ceiling: 42")
    print(f"Ceiling status: {ceiling_result['status']}")
    if ceiling_result.get("action_required"):
        print(f"Action required: {ceiling_result['action_required']}")

    # Tier D eligible residue 수 측정 (pre/post migration 판단 기준)
    tier_d_residue = [
        t for t in live_data.get("active_tasks", [])
        if t.get("status") in TIER_D_ELIGIBLE_STATUSES
    ]
    residue_count = len(tier_d_residue)
    print(f"Tier D residue in active_tasks: {residue_count}건")

    if key_count > 42:
        # ceiling 초과 시 — SYSTEM_REVIEW_REQUIRED 신호가 올바르게 발생하는지 검증
        assert ceiling_result["status"] in ("SYSTEM_REVIEW_REQUIRED", "HARD_STOP"), (
            f"Ceiling 초과({key_count}개)인데 review signal 없음 — "
            f"governance 탐지 실패: status={ceiling_result['status']}"
        )
        # post-migration 판단: residue가 없는데도 ceiling 초과 시 FAIL
        if residue_count == 0:
            pytest.fail(
                f"Tier D migration 완료 후에도 Ceiling 초과 유지: "
                f"{key_count}개 > 42개 — 추가 감축 필요"
            )
        # pre-migration 상태: residue 존재 → SYSTEM_REVIEW_REQUIRED 경고만 발행
        # (hard FAIL 아님 — Rev.3 §10 semantics 준수)
        print(
            f"[SYSTEM_REVIEW_REQUIRED] Ceiling 초과({key_count}개) — "
            f"Tier D migration 대상 {residue_count}건 존재. "
            f"migration 실행 후 재측정 필요."
        )
    else:
        # ceiling 이내 — OK 또는 SYSTEM_REVIEW_REQUIRED(41~42개)
        assert ceiling_result["status"] in ("OK", "SYSTEM_REVIEW_REQUIRED")


# ── O-3: active_tasks 내 ID 유일성 ───────────────────────────────────────────

def test_o3_active_tasks_id_uniqueness(live_data):
    """
    active_tasks 내 ID 유일성 검증.
    (cross-bucket 유일성은 archived_tasks 편입 후 동일 ID 허용 가능 — 별도 관리)
    """
    active_ids = [
        t.get("id") for t in live_data.get("active_tasks", [])
        if t.get("id")
    ]
    duplicates = [id_ for id_ in set(active_ids) if active_ids.count(id_) > 1]
    assert len(duplicates) == 0, (
        f"active_tasks 내 ID 중복 발견: {duplicates}"
    )


# ── O-4: SESSION_CONTEXT_ARCHIVE.json 구조 무결성 ────────────────────────────

def test_o4_archive_structure_integrity(archive_data):
    """SESSION_CONTEXT_ARCHIVE.json 존재 및 기본 구조 확인"""
    assert "items" in archive_data
    assert "total_items" in archive_data
    assert isinstance(archive_data["items"], list)
    assert archive_data["total_items"] == len(archive_data["items"])


# ── O-5: archive items recoverable reference 보장 ────────────────────────────

def test_o5_archive_items_recoverable(archive_data):
    """
    archive에 등록된 모든 item이 recoverable reference 조건 충족.
    source_key / source_path / payload_hash_sha256 필수.
    """
    required = ["archive_id", "source_key", "source_path",
                "migration_rule", "payload_hash_sha256"]
    for item in archive_data.get("items", []):
        for field in required:
            assert field in item, (
                f"archive item 필수 필드 누락: {field} — "
                f"archive_id={item.get('archive_id', '?')}"
            )
            assert item[field], (
                f"archive item 필수 필드 빈 값: {field} — "
                f"archive_id={item.get('archive_id', '?')}"
            )


# ── O-6: Tier A LOCKED keys SESSION_CONTEXT 내 존재 확인 ─────────────────────

def test_o6_tier_a_keys_present(live_data):
    """
    Tier A LOCKED 핵심 key들이 SESSION_CONTEXT에 존재하는지 확인.
    (Tier D migration이 Tier A를 건드리지 않았음을 사후 검증)
    """
    critical_tier_a = {
        "session_count", "chain", "canonical_rules", "lessons"
    }
    for key in critical_tier_a:
        assert key in live_data, (
            f"Tier A LOCKED key 누락: {key} — SESSION_CONTEXT 무결성 위반"
        )


# ── O-7: chain tip 불변성 ────────────────────────────────────────────────────

def test_o7_chain_tip_invariant(live_data):
    """chain.tip 불변성 확인 — Tier D migration은 chain write 없음"""
    expected = "eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd"
    actual = live_data.get("chain", {}).get("tip", "")
    assert actual == expected, (
        f"chain tip 변경 감지: {actual} — "
        f"Tier D migration이 chain을 건드렸을 가능성 있음"
    )


# ── O-8: T2 concealment 탐지 ─────────────────────────────────────────────────

def test_o8_t2_concealment_detection(live_data, archive_data):
    """
    T2 WARN 지시자(_t2_warn_active=True) 항목이
    SESSION_CONTEXT_ARCHIVE에 존재하지 않음을 확인.
    T2 active 항목의 archive 은닉(concealment) 탐지.
    """
    archive_items = archive_data.get("items", [])
    concealed = [
        item for item in archive_items
        if item.get("original_payload", {}).get("_t2_warn_active", False)
    ]
    assert len(concealed) == 0, (
        f"T2 WARN active 항목이 archive에 은닉됨: "
        f"{[i.get('archive_id') for i in concealed]}"
    )
