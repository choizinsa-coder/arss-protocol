"""
test_governance_checker.py
governance_checker v1.0 Rev.2 pytest
minimum_test_cases = 22
critical_path_coverage = 100%
S103 EAG-1 승인 — 비오(Joshua)
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

# governance_checker.py 위치: tools/governance/
# pytest rootdir: /opt/arss/engine/arss-protocol
_GOVERNANCE_DIR = Path(__file__).parent.parent / "tools" / "governance"
if str(_GOVERNANCE_DIR) not in sys.path:
    sys.path.insert(0, str(_GOVERNANCE_DIR))


# ── 헬퍼: 최소 유효 Registry fixture ─────────────────────────────────────────

def _make_dep_registry(entries=None) -> dict:
    return {
        "registry_id": "APPROVED_DEP_REGISTRY_v1.0",
        "status": "EAG_1_APPROVED",
        "entries": entries or [
            {
                "package_name": "pytest",
                "version_range": ">=9.0.0",
                "reason": "test framework",
                "owning_module": "tests/",
                "transitive_dependency_count": 0,
                "transitive_deps": [],
                "security_review_status": "PASS",
                "approved_by": "비오(Joshua)",
                "approved_session": "기존 운영 승인",
                "last_audit_session": 100,
                "replacement_reviewed": False,
            }
        ],
    }


def _make_lex_registry(entries=None) -> dict:
    return {
        "registry_id": "LEGACY_EXCEPTION_REGISTRY_v1.0",
        "status": "EAG_1_APPROVED",
        "entries": entries or [],
    }


def _make_lex_entry(exception_id="LEX-001", expiry_policy=None, classification="DELETION_REVIEW", module_or_file="99_LEGACY/some_backup.py") -> dict:
    entry = {
        "exception_id": exception_id,
        "module_or_file": module_or_file,
        "violated_rule": "RULE-5",
        "reason": "test entry",
        "risk_level": "LOW",
        "classification": classification,
        "delete_ready": False,
    }
    if expiry_policy is not None:
        entry["expiry_policy"] = expiry_policy
    return entry


def _run_check(dep_entries=None, lex_entries=None, current_session="S103", requesting_agent_id=None, tmp_path=None):
    """governance_checker.run_governance_check를 fixture 기반으로 실행."""
    from governance_checker import run_governance_check

    dep_data = _make_dep_registry(dep_entries)
    lex_data = _make_lex_registry(lex_entries)

    dep_file = tmp_path / "approved_dependency_registry_v1.0.json"
    lex_file = tmp_path / "legacy_exception_registry_v1.0.json"
    dep_file.write_text(json.dumps(dep_data), encoding="utf-8")
    lex_file.write_text(json.dumps(lex_data), encoding="utf-8")

    return run_governance_check(
        current_session=current_session,
        requesting_agent_id=requesting_agent_id,
        approved_dep_registry_path=dep_file,
        legacy_exception_registry_path=lex_file,
    )


# ── TC-1~12: 기본 검증 ────────────────────────────────────────────────────────

class TestBasicValidation:

    def test_tc1_clean_registries_pass(self, tmp_path):
        """TC-1: 정상 Registry → PASS T0"""
        result = _run_check(tmp_path=tmp_path)
        assert result["verdict"] == "PASS"
        assert result["stop_required"] is False

    def test_tc2_receipt_id_present(self, tmp_path):
        """TC-2: R1 Receipt receipt_id 존재"""
        result = _run_check(tmp_path=tmp_path)
        assert "receipt_id" in result
        assert result["receipt_id"] != ""

    def test_tc3_receipt_scope_r1(self, tmp_path):
        """TC-3: Receipt Scope = R1"""
        result = _run_check(tmp_path=tmp_path)
        assert result["receipt_scope"] == "R1"

    def test_tc4_awareness_metadata_fields(self, tmp_path):
        """TC-4: Awareness Metadata 허용 필드만 포함"""
        result = _run_check(tmp_path=tmp_path)
        meta = result["awareness_metadata"]
        allowed = {"registry_version", "registry_hash", "validation_timestamp", "verdict", "risk_tier", "receipt_id", "requesting_agent_id"}
        for key in meta:
            assert key in allowed, f"금지 필드 노출: {key}"

    def test_tc5_registry_body_not_in_awareness(self, tmp_path):
        """TC-5: Registry body가 Awareness Metadata에 노출되지 않음"""
        result = _run_check(tmp_path=tmp_path)
        meta = result["awareness_metadata"]
        assert "entries" not in meta
        assert "package_name" not in str(meta)

    def test_tc6_security_review_pending_review(self, tmp_path):
        """TC-6: security_review_status PENDING → REVIEW T1"""
        entries = [{
            "package_name": "Flask",
            "version_range": ">=3.1.0",
            "reason": "HTTP server",
            "owning_module": "aiba_status_server.py",
            "transitive_dependency_count": 0,
            "transitive_deps": [],
            "security_review_status": "PENDING",
            "approved_by": None,
            "approved_session": None,
            "last_audit_session": 100,
            "replacement_reviewed": False,
        }]
        result = _run_check(dep_entries=entries, tmp_path=tmp_path)
        assert result["verdict"] == "REVIEW"

    def test_tc7_requesting_agent_id_caddy_included(self, tmp_path):
        """TC-7: requesting_agent_id=caddy → Awareness Metadata에 포함"""
        result = _run_check(requesting_agent_id="caddy", tmp_path=tmp_path)
        assert result["awareness_metadata"].get("requesting_agent_id") == "caddy"

    def test_tc8_requesting_agent_id_unknown_review(self, tmp_path):
        """TC-8: 알 수 없는 requesting_agent_id → REVIEW"""
        result = _run_check(requesting_agent_id="unknown_bot", tmp_path=tmp_path)
        assert result["verdict"] == "REVIEW"

    def test_tc9_requesting_agent_id_not_affect_verdict(self, tmp_path):
        """TC-9: requesting_agent_id 유효 → verdict 변경 없음 (PASS 유지)"""
        result_no_agent = _run_check(tmp_path=tmp_path)
        result_with_agent = _run_check(requesting_agent_id="domi", tmp_path=tmp_path)
        assert result_no_agent["verdict"] == result_with_agent["verdict"]

    def test_tc10_findings_list_present(self, tmp_path):
        """TC-10: findings 리스트 존재"""
        result = _run_check(tmp_path=tmp_path)
        assert "findings" in result
        assert isinstance(result["findings"], list)

    def test_tc11_valid_session_format(self, tmp_path):
        """TC-11: 유효한 current_session 형식 → 정상 처리"""
        result = _run_check(current_session="S103", tmp_path=tmp_path)
        assert result["verdict"] != "FAIL" or result["stop_reason"] not in (
            "CURRENT_SESSION_MISSING", "CURRENT_SESSION_MALFORMED"
        )

    def test_tc12_no_registry_mutation(self, tmp_path):
        """TC-12: 실행 후 Registry 파일 내용 불변"""
        dep_data = _make_dep_registry()
        lex_data = _make_lex_registry()
        dep_file = tmp_path / "approved_dependency_registry_v1.0.json"
        lex_file = tmp_path / "legacy_exception_registry_v1.0.json"
        dep_content = json.dumps(dep_data)
        lex_content = json.dumps(lex_data)
        dep_file.write_text(dep_content, encoding="utf-8")
        lex_file.write_text(lex_content, encoding="utf-8")

        from governance_checker import run_governance_check
        run_governance_check(
            current_session="S103",
            approved_dep_registry_path=dep_file,
            legacy_exception_registry_path=lex_file,
        )

        assert dep_file.read_text(encoding="utf-8") == dep_content
        assert lex_file.read_text(encoding="utf-8") == lex_content


# ── TC-13~17: expiry_policy 판정 ──────────────────────────────────────────────

class TestExpiryPolicy:

    def test_tc13_expiry_policy_missing_review_t1(self, tmp_path):
        """TC-13: expiry_policy missing → REVIEW T1, no STOP"""
        entry = _make_lex_entry("LEX-001")  # expiry_policy 없음
        result = _run_check(lex_entries=[entry], tmp_path=tmp_path)
        lex_finding = next((f for f in result["findings"] if f["target"] == "LEX-001"), None)
        assert lex_finding is not None
        assert lex_finding["verdict"] == "REVIEW"
        assert lex_finding["risk_tier"] == "T1"
        assert lex_finding["stop_required"] is False
        assert lex_finding["review_reason"] == "EXPIRY_POLICY_MISSING"

    def test_tc14_date_expired_fail_t3_stop(self, tmp_path):
        """TC-14: DATE 만료 → T3 FAIL + STOP"""
        entry = _make_lex_entry("LEX-001", expiry_policy={
            "type": "DATE",
            "expiry_date": "2020-01-01",
            "expiry_session": None,
            "condition": None,
        })
        result = _run_check(lex_entries=[entry], tmp_path=tmp_path)
        lex_finding = next((f for f in result["findings"] if f["target"] == "LEX-001"), None)
        assert lex_finding["verdict"] == "FAIL"
        assert lex_finding["risk_tier"] == "T3"
        assert lex_finding["stop_required"] is True
        assert lex_finding["stop_reason"] == "EXPIRED_EXCEPTION_STOP"

    def test_tc15_date_not_expired_pass(self, tmp_path):
        """TC-15: DATE 미만료 → no expiry STOP"""
        entry = _make_lex_entry("LEX-001", expiry_policy={
            "type": "DATE",
            "expiry_date": "2099-12-31",
            "expiry_session": None,
            "condition": None,
        })
        result = _run_check(lex_entries=[entry], tmp_path=tmp_path)
        lex_finding = next((f for f in result["findings"] if f["target"] == "LEX-001"), None)
        assert lex_finding["stop_reason"] != "EXPIRED_EXCEPTION_STOP"

    def test_tc16_session_expired_fail_t3_stop(self, tmp_path):
        """TC-16: SESSION 만료 → T3 FAIL + STOP"""
        entry = _make_lex_entry("LEX-001", expiry_policy={
            "type": "SESSION",
            "expiry_date": None,
            "expiry_session": "S50",
            "condition": None,
        })
        result = _run_check(lex_entries=[entry], current_session="S103", tmp_path=tmp_path)
        lex_finding = next((f for f in result["findings"] if f["target"] == "LEX-001"), None)
        assert lex_finding["verdict"] == "FAIL"
        assert lex_finding["risk_tier"] == "T3"
        assert lex_finding["stop_required"] is True
        assert lex_finding["stop_reason"] == "EXPIRED_EXCEPTION_STOP"

    def test_tc17_condition_expiry_review_t1(self, tmp_path):
        """TC-17: CONDITION expiry → REVIEW T1, no STOP"""
        entry = _make_lex_entry("LEX-001", expiry_policy={
            "type": "CONDITION",
            "expiry_date": None,
            "expiry_session": None,
            "condition": "rpu_atomic_issuer 리팩토링 완료 시",
        })
        result = _run_check(lex_entries=[entry], tmp_path=tmp_path)
        lex_finding = next((f for f in result["findings"] if f["target"] == "LEX-001"), None)
        assert lex_finding["verdict"] == "REVIEW"
        assert lex_finding["risk_tier"] == "T1"
        assert lex_finding["stop_required"] is False


# ── TC-18~20: Cross-Registry + Agent ─────────────────────────────────────────

class TestCrossRegistryAndAgent:

    def test_tc18_approved_dep_conflicts_legacy_fail_stop(self, tmp_path):
        """TC-18: approved dependency가 legacy exception과 충돌 → FAIL + STOP"""
        dep_entries = [{
            "package_name": "some_pkg",
            "version_range": ">=1.0.0",
            "reason": "test",
            "owning_module": "tools/",
            "transitive_dependency_count": 0,
            "transitive_deps": [],
            "security_review_status": "PASS",
            "approved_by": "비오(Joshua)",
            "approved_session": "S103",
            "last_audit_session": 103,
            "replacement_reviewed": False,
        }]
        lex_entries = [_make_lex_entry(
            "LEX-001",
            classification="QUARANTINED",
            module_or_file="99_LEGACY/some_pkg_backup.py",
        )]
        result = _run_check(dep_entries=dep_entries, lex_entries=lex_entries, tmp_path=tmp_path)
        conflict_finding = next(
            (f for f in result["findings"] if f.get("stop_reason") == "CROSS_REGISTRY_CONFLICT_STOP"), None
        )
        assert conflict_finding is not None
        assert conflict_finding["verdict"] == "FAIL"
        assert conflict_finding["stop_required"] is True

    def test_tc19_transitive_dep_conflicts_legacy_fail_stop(self, tmp_path):
        """TC-19: transitive dependency가 legacy exception과 충돌 → FAIL + STOP"""
        dep_entries = [{
            "package_name": "Flask",
            "version_range": ">=3.1.0",
            "reason": "HTTP server",
            "owning_module": "aiba_status_server.py",
            "transitive_dependency_count": 1,
            "transitive_deps": ["Werkzeug"],
            "security_review_status": "PASS",
            "approved_by": "비오(Joshua)",
            "approved_session": "S103",
            "last_audit_session": 103,
            "replacement_reviewed": False,
        }]
        lex_entries = [_make_lex_entry(
            "LEX-001",
            classification="QUARANTINED",
            module_or_file="99_LEGACY/Werkzeug_backup.py",
        )]
        result = _run_check(dep_entries=dep_entries, lex_entries=lex_entries, tmp_path=tmp_path)
        conflict_finding = next(
            (f for f in result["findings"] if f.get("stop_reason") == "CROSS_REGISTRY_CONFLICT_STOP"), None
        )
        assert conflict_finding is not None
        assert conflict_finding["stop_required"] is True

    def test_tc20_requesting_agent_id_projection_only_not_verdict(self, tmp_path):
        """TC-20: requesting_agent_id는 projection만 변경, verdict 불변"""
        result_no = _run_check(tmp_path=tmp_path)
        result_caddy = _run_check(requesting_agent_id="caddy", tmp_path=tmp_path)
        result_jeni = _run_check(requesting_agent_id="jeni", tmp_path=tmp_path)
        assert result_no["verdict"] == result_caddy["verdict"] == result_jeni["verdict"]


# ── TC-21~22: current_session 계약 ───────────────────────────────────────────

class TestCurrentSessionContract:

    def test_tc21_session_expiry_missing_current_session_fail_t2(self, tmp_path):
        """TC-21: SESSION expiry + current_session missing → T2 FAIL + STOP"""
        entry = _make_lex_entry("LEX-001", expiry_policy={
            "type": "SESSION",
            "expiry_date": None,
            "expiry_session": "S50",
            "condition": None,
        })
        result = _run_check(lex_entries=[entry], current_session=None, tmp_path=tmp_path)
        assert result["stop_required"] is True
        cs_finding = next(
            (f for f in result["findings"] if f.get("stop_reason") == "CURRENT_SESSION_MISSING"), None
        )
        assert cs_finding is not None
        assert cs_finding["risk_tier"] == "T2"

    def test_tc22_session_expiry_malformed_current_session_fail_t2(self, tmp_path):
        """TC-22: SESSION expiry + malformed current_session → T2 FAIL + STOP"""
        entry = _make_lex_entry("LEX-001", expiry_policy={
            "type": "SESSION",
            "expiry_date": None,
            "expiry_session": "S50",
            "condition": None,
        })
        result = _run_check(lex_entries=[entry], current_session="INVALID_FORMAT", tmp_path=tmp_path)
        assert result["stop_required"] is True
        cs_finding = next(
            (f for f in result["findings"] if f.get("stop_reason") == "CURRENT_SESSION_MALFORMED"), None
        )
        assert cs_finding is not None
        assert cs_finding["risk_tier"] == "T2"
