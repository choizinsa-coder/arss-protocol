"""
test_boundary_enforcement_validator.py
PT-S81-ARCH-001 Phase 2 — boundary_enforcement_validator 테스트
Domi spec 기준 PASS/FAIL 조건 전체 검증
"""
import sys

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.session_context_gen.boundary_enforcement_validator import (
    validate_agent_boundaries,
)


def _valid_manifest():
    return {
        "domi": ["SESSION_BOOT"],
        "jeni": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
        "caddy": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
        "normal_upload_bundle": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
    }


# ── TC-1: 정상 PASS ─────────────────────────────────────────────────────────────

def test_tc1_valid_manifest_pass():
    result = validate_agent_boundaries(_valid_manifest())
    assert result["pass"] is True, f"TC-1 FAIL: {result['errors']}"
    assert result["validator"] == "boundary_enforcement_validator"
    assert result["errors"] == []


# ── TC-2: 빈 manifest ────────────────────────────────────────────────────────

def test_tc2_empty_manifest_fail():
    result = validate_agent_boundaries({})
    assert result["pass"] is False
    assert any("missing or empty" in e for e in result["errors"])


# ── TC-3: Domi가 RUNTIME 수신 ────────────────────────────────────────────────

def test_tc3_domi_receives_runtime_fail():
    m = _valid_manifest()
    m["domi"] = ["SESSION_BOOT", "SESSION_STATE_RUNTIME"]
    result = validate_agent_boundaries(m)
    assert result ["pass"] is False
    assert any("Domi receives SESSION_STATE_RUNTIME" in e for e in result["errors"])


# ── TC-4: Dof�ʬ FULL 수신 ────────────────────────────────────────────────────

def test_tc4_domi_receives_full_fail():
    m = _valid_manifest()
    m["domi"] = ["SESSION_BOOT", "SESSION_CONTEXT_FULL"]
    result = validate_agent_boundaries(m)
    assert result["pass"] is False
    assert any("SESSION_CONTEXT_FULL" in e for e in result["errors"])


# ── TC-5: normal_upload_bundle에 FULL 포함 ───────────────────────────────────

def test_tc5_normal_bundle_contains_full_fail():
    m = _valid_manifest()
    m["normal_upload_bundle"] = ["SESSION_BOOT", "SESSION_STATE_RUNTIME", "SESSION_CONTEXT_FULL"]
    result = validate_agent_boundaries(m)
    assert result["pass"] is False
    assert any("normal_upload_bundle" in e for e in result["errors"])


# ── TC-6: agent routing map 항목 누락 ─────────────────────────────────────────

def test_tc6_missing_agent_entry_fail():
    m = _valid_manifest()
    del m["jeni"]
    result = validate_agent_boundaries(m)
    assert result["pass"] is False
    assert any("missing entry for 'jeni'" in e for e in result["errors"])


# ── TC-7: Jeni가 BOOT 누락 ───────────────────────────────────────────────────

def test_tc7_jeni_missing_boot_fail():
    m = _valid_manifest()
    m["jeni"] = ["SESSION_STATE_RUNTIME"]
    result = validate_agent_boundaries(m)
    assert result["pass"] is False
    assert any("'jeni' does not receive SESSION_BOOT" in e for e in result["errors"])


# ── TC-8: Caddy가 RUNTIME 누락 ────────────────────────────────────────────────

def test_tc8_caddy_missing_runtime_fail():
    m = _valid_manifest()
    m["caddy"] = ["SESSION_BOOT"]
    result = validate_agent_boundaries(m)
    assert result["pass"] is False
    assert any("'caddy' does not receive SESSION_STATE_RUNTIME" in e for e in result["errors"])


# ── TC-9: emergency_fallback + beo_approval → FULL 빈용 (WARNING only) ────────

def test_tc9_emergency_fallback_with_beo_approval_warning():
    m = _valid_manifest()
    m["domi"] = ["SESSION_BOOT", "SESSION_CONTEXT_FULL"]
    m["emergency_fallback"] = True
    m["beo_approval_flag"] = True
    result = validate_agent_boundaries(m)
    # Domi receiving RUNTIME is still FAIL; but FULL under emergency is WARNING
    # Domi does not receive RUNTIME here, so only FULL check applies
    assert any("WARNING" in w for w in result['warnings'])


# ── TC-10: 미증의 에이전트 삤에 FULL 포함 → 경계 모호 ────────────────────────

def test_tc10_unknown_agent_with_full_fail():
    m = _valid_manifest()
    m["unknown_agent"] = ["SESSION_BOOT", "SESSION_CONTEXT_FULL"]
    result = validate_agent_boundaries(m)
    assert result["pass"] is False
    assert any("boundary is ambiguous" in e for e in result["errors"])
