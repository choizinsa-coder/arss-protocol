"""
test_agent_injection_manifest.py
PT-S81-ARCH-001 Phase 2 Step 9 — pytest

TC-1: generate_manifest() 반환값 구조 정확성
TC-2: 정상 manifest → validate PASS
TC-3: Domi = BOOT only → PASS
TC-4: Domi에 RUNTIME 추가 → FAIL
TC-5: Jeni = BOOT + RUNTIME → PASS
TC-6: Jeni에서 RUNTIME 제거 → FAIL
TC-7: Caddy = BOOT + RUNTIME → PASS
TC-8: FULL이 normal_upload_bundle에 포함 → FAIL
TC-9: agent key 누락 → FAIL
TC-10: FULL이 caddy에 포함 → FAIL
"""

import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
import pytest
from tools.session_context_gen.agent_injection_manifest import generate_manifest, validate_manifest


# TC-1: generate_manifest() 구조 확인
def test_tc1_generate_manifest_structure():
    m = generate_manifest()
    assert "domi" in m
    assert "jeni" in m
    assert "caddy" in m
    assert "normal_upload_bundle" in m


# TC-2: 정상 manifest → PASS
def test_tc2_valid_manifest_pass():
    m = generate_manifest()
    result = validate_manifest(m)
    assert result["pass"] is True
    assert result["errors"] == []


# TC-3: Domi = BOOT only → PASS
def test_tc3_domi_boot_only_pass():
    m = generate_manifest()
    assert m["domi"] == ["SESSION_BOOT"]
    result = validate_manifest(m)
    assert result["pass"] is True


# TC-4: Domi에 RUNTIME 추가 → FAIL
def test_tc4_domi_with_runtime_fail():
    m = generate_manifest()
    m["domi"] = ["SESSION_BOOT", "SESSION_STATE_RUNTIME"]
    result = validate_manifest(m)
    assert result["pass"] is False
    assert any("domi" in e for e in result["errors"])


# TC-5: Jeni = BOOT + RUNTIME → PASS
def test_tc5_jeni_boot_runtime_pass():
    m = generate_manifest()
    assert set(m["jeni"]) == {"SESSION_BOOT", "SESSION_STATE_RUNTIME"}
    result = validate_manifest(m)
    assert result["pass"] is True


# TC-6: Jeni에서 RUNTIME 제거 → FAIL
def test_tc6_jeni_missing_runtime_fail():
    m = generate_manifest()
    m["jeni"] = ["SESSION_BOOT"]
    result = validate_manifest(m)
    assert result["pass"] is False
    assert any("jeni" in e for e in result["errors"])


# TC-7: Caddy = BOOT + RUNTIME → PASS
def test_tc7_caddy_boot_runtime_pass():
    m = generate_manifest()
    assert set(m["caddy"]) == {"SESSION_BOOT", "SESSION_STATE_RUNTIME"}
    result = validate_manifest(m)
    assert result["pass"] is True


# TC-8: FULL이 normal_upload_bundle에 포함 → FAIL
def test_tc8_full_in_normal_bundle_fail():
    m = generate_manifest()
    m["normal_upload_bundle"].append("SESSION_CONTEXT_FULL")
    result = validate_manifest(m)
    assert result["pass"] is False
    assert any("SESSION_CONTEXT_FULL" in e for e in result["errors"])


# TC-9: agent key 누락 → FAIL
def test_tc9_missing_agent_key_fail():
    m = generate_manifest()
    del m["caddy"]
    result = validate_manifest(m)
    assert result["pass"] is False
    assert any("caddy" in e for e in result["errors"])


# TC-10: FULL이 caddy에 포함 → FAIL
def test_tc10_full_in_caddy_fail():
    m = generate_manifest()
    m["caddy"].append("SESSION_CONTEXT_FULL")
    result = validate_manifest(m)
    assert result["pass"] is False
    assert any("SESSION_CONTEXT_FULL" in e and "caddy" in e for e in result["errors"])
