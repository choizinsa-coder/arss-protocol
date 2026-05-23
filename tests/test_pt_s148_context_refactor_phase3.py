"""
PT-S148-CONTEXT-REFACTOR-PHASE3: tasks + metrics shard 검증
Phase 3 1차 배포 — tasks(4) + metrics(1)
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

EXPECTED_HASHES = {
    "active":   "9e69206d98864be39a4f5f40d61103d5dcfb9978c367cc8e8414e841af5e4d6a",
    "hold":     "84c2a0f150d7420538afaa31e7d676ddb9cb92a1bf88ceec78bfd62f3633f657",
    "blocked":  "d3071cdf66b03d4077f5c093d00bc89865821780b95fe9cafd61e2db12336d71",
    "pending":  "43fb0ffa647dcd73fb1552ad34148ffa988df33dd8074d252ff62815d584c0e1",
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


# ── T-2: hash 무결성 검증 ────────────────────────────────────────
def test_t2_active_hash_integrity():
    content, _ = _load("active")
    assert _sha256(content) == EXPECTED_HASHES["active"]

def test_t3_hold_hash_integrity():
    content, _ = _load("hold")
    assert _sha256(content) == EXPECTED_HASHES["hold"]

def test_t4_blocked_hash_integrity():
    content, _ = _load("blocked")
    assert _sha256(content) == EXPECTED_HASHES["blocked"]

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
    # active shard에 items 존재
    assert isinstance(items, list)
    assert len(items) > 0


# ── T-10: visibility_history 구조 검증 ───────────────────────────
def test_t10_visibility_history_structure():
    _, body = _load("visibility_history")
    history = body.get("history", {})
    assert isinstance(history, dict)
    # 6개 세션 포함
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


# ── T-12: SESSION_CONTEXT pointer 교체 검증 ──────────────────────
def test_t12_session_context_pointer_structure():
    sc_path = f"{BASE}/SESSION_CONTEXT.json"
    with open(sc_path, "r", encoding="utf-8") as f:
        sc = json.load(f)

    pointer_keys = ["active_tasks", "hold_tasks", "blocked_tasks", "pending_tasks"]
    for key in pointer_keys:
        entry = sc.get(key, {})
        assert isinstance(entry, dict), f"{key}가 dict(pointer)가 아님"
        assert "body_ref" in entry, f"{key}: body_ref 없음"
        assert "_shard_hash" in entry, f"{key}: _shard_hash 없음"

    # visibility_metrics pointer
    vm_pointer = sc.get("visibility_metrics_current")
    assert vm_pointer is not None, "visibility_metrics_current pointer 없음"
    assert "body_ref" in vm_pointer
