"""
test_canonset_s250.py
DEP-S250-CANONSET-001 검증 TC (EAG-S250-CANONSET-001)
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(rel):
    path = os.path.join(ROOT, rel)
    spec = importlib.util.spec_from_file_location(os.path.basename(rel)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ARCH = _load("tools/session_context_gen/session_context_archive.py")
CLOSE = _load("tools/close/session_close_generator.py")


def test_canonical_exclude_keys_is_9():
    assert len(ARCH.CANONICAL_EXCLUDE_KEYS) == 9
    assert "next_steps" not in ARCH.CANONICAL_EXCLUDE_KEYS  # 내용 키는 카운트 유지
    assert "agent_focus" not in ARCH.CANONICAL_EXCLUDE_KEYS
    assert "session_reentry" not in ARCH.CANONICAL_EXCLUDE_KEYS
    assert "session_count" in ARCH.CANONICAL_EXCLUDE_KEYS


def test_canonical_key_count_excludes_machine_keys():
    sc = {k: 1 for k in ARCH.CANONICAL_EXCLUDE_KEYS}
    sc.update({"next_steps": 1, "agent_focus": 1, "active_tasks": 1})
    assert ARCH.canonical_key_count(sc) == 3  # 9 제외, 3 내용 키만 카운트


def test_ceiling_hard_stop_over_42():
    sc = {f"k{i}": 1 for i in range(45)}  # 제외 키 없음 → 45 canonical
    r = ARCH._check_complexity_ceiling(sc)
    assert r["status"] == "HARD_STOP"


def test_ceiling_override_downgrades_to_review():
    sc = {f"k{i}": 1 for i in range(45)}
    r = ARCH._check_complexity_ceiling(sc, override_approved=True)
    assert r["status"] == "SYSTEM_REVIEW_REQUIRED"


def test_ceiling_ok_at_40():
    sc = {f"k{i}": 1 for i in range(40)}
    r = ARCH._check_complexity_ceiling(sc)
    assert r["status"] == "OK"


def test_group_d_whitelist_is_4():
    assert len(CLOSE.GROUP_D_MIGRATE_WHITELIST) == 4
    assert "goal2_progress" not in CLOSE.GROUP_D_MIGRATE_WHITELIST  # 위험 키 active 유지


def test_identify_includes_group_d():
    sc = {
        "goal2_declaration": {"x": 1},
        "goal2_progress": {"y": 1},          # 비대상
        "caddy_governance_record_s100": {"z": 1},  # aged record (n=250 → 이관)
        "active_tasks": {"a": 1},            # 비대상
    }
    cands = CLOSE.identify_archive_candidates(sc, n=250)
    assert "goal2_declaration" in cands       # group D 이관
    assert "caddy_governance_record_s100" in cands  # aged record 이관
    assert "goal2_progress" not in cands      # 위험 키 유지
    assert "active_tasks" not in cands        # 구조 키 유지


def test_tier_a_locked_removed_noncanonical():
    assert "ssoi_status" not in ARCH.TIER_A_LOCKED_KEYS
    assert "activation_allowed" not in ARCH.TIER_A_LOCKED_KEYS
    assert "session_open_rules" not in ARCH.TIER_A_LOCKED_KEYS
    assert "session_close_rules" not in ARCH.TIER_A_LOCKED_KEYS
    assert "architecture" in ARCH.TIER_A_LOCKED_KEYS  # 실측 보류 유지
