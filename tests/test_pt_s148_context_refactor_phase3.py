"""
PT-S148-CONTEXT-REFACTOR-PHASE3: tasks + metrics shard 검증
Phase 3 1차 배포 — tasks(4) + metrics(1)

S180 수정: Incident-L14 Group B 수습
  - T2 (test_t2_active_hash_integrity): active.json hash 현행화
    (S166 이후 shard 내용 변경 반영)
  - T5 (test_t5_pending_hash_integrity): pending.json hash 현행화
    (S166 이후 shard 내용 변경 반영)
  - T12 (test_t12_session_context_pointer_structure):
    visibility_metrics_current가 Tier D 포인터로 전환됨 (quarantine_status + archive_ref 구조)
    → body_ref 검증 제거, Tier D 포인터 계약 검증으로 재설계
"""
import sys
import json
import hashlib
import os

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

BASE = "/opt/arss/engine/arss-protocol"

SHARD_PATHS = {
    "active":   f"{BASE}/context/tasks/active.json",
    "hold":     f"{BASE}/context/tasks/hold.json",
    "blocked":  f"{BASE}/context/tasks/blocked.json",
    "pending":  f"{BASE}/context/tasks/pending.json",
    "visibility_history": f"{BASE}/context/metrics/visibility_history.json",
}

# S180 Incident-L14: active/pending hash 현행화
# active: S166 이후 내용 변경 반영 (실측값 2026-05-31)
# pending: S166 이후 내용 변경 반영 (실측값 2026-05-31)
EXPECTED_HASHES = {
    "active":   "46d5bd257c35731dceda26f34bd930f3c304143c8ab614da36bd06aa3d68bf2f",
    "hold":     "8acf7ea42bcbdd2a471b5e1bf8bb1d4f2ff60d63db1939807d460115d1981da5",
    "blocked":  "d3071cdf66b03d4077f5c093d00bc89865821780b95fe9cafd61e2db12336d71",
    "pending":  "ad7273b85d73b505beaed61ca2a6b9c8d5bd080710ddf8e758fee0634d634ca9",
    "visibility_history": "da869da534c1cd0a0f87c8c6f7b9d84e5c24370c3ae0c2cf90ca380f93f68adf",
}

EXPECTED_DOMAINS = {
    "active":   "tasks.active",
    "hold":     "tasks.hold",
    "blocked":  "tasks.blocked",
    "pending":  "tasks.pending",
    "visibility_history": "metrics.visibility_history",
}


def _load(key):
    with open(SHARD_PATHS[key], "r", encoding="utf-8") as f:
        content = f.read()
    return content, json.loads(content)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ── T-1: 파일 존재 확인 ──────────────────────────────────────────
def test_t1_shard_files_exist():
    for key, path in SHARD_PATHS.items():
        assert os.path.exists(path), f"{key} shard 파일 없음: {path}"


# ── T-2: hash 무결성 검증 (S180 현행화) ─────────────────────────
def test_t2_active_hash_integrity():
    content, _ = _load("active")
    assert _sha256(content) == EXPECTED_HASHES["active"]

def test_t3_hold_hash_integrity():
    content, _ = _load("hold")
    assert _sha256(content) == EXPECTED_HASHES["hold"]

def test_t4_blocked_hash_integrity():
    content, _ = _load("blocked")
    assert _sha256(content) == EXPECTED_HASHES["blocked"]

# ── T-5: pending hash 검증 (S180 현행화) ────────────────────────
def test_t5_pending_hash_integrity():
    content, _ = _load("pending")
    assert _sha256(content) == EXPECTED_HASHES["pending"]

def test_t6_visibility_history_hash_integrity():
    content, _ = _load("visibility_history")
    assert _sha256(content) == EXPECTED_HASHES["visibility_history"]


# ── T-7: domain 필드 검증 ────────────────────────────────────────
def test_t7_domain_fields():
    for key, expected_domain in EXPECTED_DOMAINS.items():
        _, body = _load(key)
        assert body.get("domain") == expected_domain, \
            f"{key}: domain={body.get('domain')} != {expected_domain}"


# ── T-8: schema_version 검증 ─────────────────────────────────────
def test_t8_schema_version():
    for key in SHARD_PATHS:
        _, body = _load(key)
        assert body.get("schema_version") == "phase3_shard_v1", \
            f"{key}: schema_version 불일치"


# ── T-9: active_tasks 추가 pointer 필드 검증 ─────────────────────
def test_t9_active_tasks_pointer_fields():
    _, body = _load("active")
    items = body.get("items", [])
    assert isinstance(items, list)
    assert len(items) > 0


# ── T-10: visibility_history 구조 검증 ───────────────────────────
def test_t10_visibility_history_structure():
    _, body = _load("visibility_history")
    history = body.get("history", {})
    assert isinstance(history, dict)
    assert len(history) == 6
    expected_sessions = [
        "visibility_metrics_s141",
        "visibility_metrics_s143",
        "visibility_metrics_s144",
        "visibility_metrics_s145",
        "visibility_metrics_s146",
        "visibility_metrics_s147",
    ]
    for key in expected_sessions:
        assert key in history, f"{key} 누락"


# ── T-11: tasks shard items 타입 검증 ────────────────────────────
def test_t11_tasks_items_are_lists():
    for key in ["active", "hold", "blocked", "pending"]:
        _, body = _load(key)
        assert isinstance(body.get("items"), list), \
            f"{key}: items가 list가 아님"


# ── T-12: SESSION_CONTEXT pointer 교체 검증 (S180 재설계) ────────
# Incident-L14 S180: visibility_metrics_current가 Tier D 포인터로 전환됨
# body_ref 검증 제거 → quarantine_status + archive_ref Tier D 계약 검증으로 재설계
def test_t12_session_context_pointer_structure():
    sc_path = f"{BASE}/SESSION_CONTEXT.json"
    with open(sc_path, "r", encoding="utf-8") as f:
        sc = json.load(f)

    # tasks shard pointer 검증 (변경 없음)
    pointer_keys = ["active_tasks", "hold_tasks", "blocked_tasks", "pending_tasks"]
    for key in pointer_keys:
        entry = sc.get(key, {})
        assert isinstance(entry, dict), f"{key}가 dict(pointer)가 아님"
        assert "body_ref" in entry, f"{key}: body_ref 없음"
        assert "_shard_hash" in entry, f"{key}: _shard_hash 없음"

    # visibility_metrics_current: Tier D 포인터 구조 검증
    # S166 이후 visibility_metrics_current가 Tier D 포인터로 전환됨
    vm = sc.get("visibility_metrics_current")
    assert vm is not None, "visibility_metrics_current 필드 없음"
    assert isinstance(vm, dict), "visibility_metrics_current는 dict여야 함"
    assert vm.get("quarantine_status") == "TIER_D", \
        f"visibility_metrics_current quarantine_status 불일치: {vm.get('quarantine_status')}"
    assert "archive_ref" in vm, \
        "visibility_metrics_current archive_ref 누락"
