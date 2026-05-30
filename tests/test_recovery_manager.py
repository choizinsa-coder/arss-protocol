"""
test_recovery_manager.py
source: tools/session_context_gen/recovery_manager.py
P4-C2 (S174): SESSION_BOOT_PENDING stub → Fixture Layer 실제 테스트 작성
원칙: dict 기반 fixture — SESSION_BOOT 파일 비의존

구조:
  RM-1: build_recovery_package_r1 정상 path — 필수 블록 포함
  RM-2: build_recovery_package_r1 — lkg_snapshot_payload 빈 dict → ValueError (failure path)
  RM-3: build_recovery_package_r1 — trigger_context 필수 필드 누락 → ValueError (failure path)
  RM-4: validate_r1_package_integrity 정상 path — 예외 없음
  RM-5: validate_r1_package_integrity — integrity_verdict 조작 → ValueError (failure path)
  RM-6: generate_recovery_candidate_r2 정상 path — candidate + receipt 반환
  RM-7: recover_baseline — RecoveryError 즉시 발생 (failure path)
"""

import sys
import unittest

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.session_context_gen.recovery_manager import (
    build_recovery_package_r1,
    validate_r1_package_integrity,
    generate_recovery_candidate_r2,
    recover_baseline,
    RecoveryError,
    calculate_canonical_hash,
)


# ── Fixture 헬퍼 ────────────────────────────────────────────────────────────

def _make_valid_trigger() -> dict:
    return {
        "trigger_reason": "BOOT_HASH_MISMATCH",
        "trigger_event_ref": "EV-001",
        "requested_by": "caddy",
        "recovery_mode": "LKG_STRICT",
    }


def _make_valid_selector() -> dict:
    return {
        "lkg_receipt_id": "RCPT-001",
        "lkg_receipt_hash": "abc123",
        "lkg_artifact_hash": "def456",
        "lkg_session_count": 170,
        "lkg_generated_at": "2026-05-30T00:00:00+09:00",
        "lkg_selection_basis": "LAST_VERIFIED",
        "lkg_selection_verdict": "SELECTED",
    }


def _make_valid_audit() -> dict:
    return {
        "candidate_pool_summary": "3 candidates",
        "rejected_candidates_summary": "2 rejected",
        "final_selection_reason": "highest session",
        "selector_version": "v1.0",
    }


def _make_valid_snapshot() -> dict:
    return {"session_count": 170, "chain_tip": "abc1234"}


def _build_valid_r1() -> dict:
    return build_recovery_package_r1(
        recovery_id="RCVR-TEST-001",
        trigger_context=_make_valid_trigger(),
        selector_result=_make_valid_selector(),
        lkg_snapshot_payload=_make_valid_snapshot(),
        created_from_session=174,
        selection_audit=_make_valid_audit(),
    )


# ── RM-1: build_recovery_package_r1 정상 path ─────────────────────────────

class TestRM1_BuildR1Valid(unittest.TestCase):
    def test_RM1_valid_r1_has_required_blocks(self):
        """유효한 r1 패키지 — 필수 블록 모두 포함 (정상 path)"""
        r1 = _build_valid_r1()
        for block in ["package_identity", "trigger_context", "selected_last_known_good",
                      "selected_last_known_good_snapshot", "selection_audit", "package_integrity"]:
            self.assertIn(block, r1)
        self.assertEqual(r1["package_integrity"]["integrity_verdict"], "PASS")


# ── RM-2: lkg_snapshot_payload 빈 dict → ValueError (failure path) ─────────

class TestRM2_EmptyPayload(unittest.TestCase):
    def test_RM2_empty_snapshot_raises_value_error(self):
        """lkg_snapshot_payload 빈 dict → ValueError (RULE-8 failure path)"""
        with self.assertRaises(ValueError) as ctx:
            build_recovery_package_r1(
                recovery_id="R",
                trigger_context=_make_valid_trigger(),
                selector_result=_make_valid_selector(),
                lkg_snapshot_payload={},  # 빈 dict
                created_from_session=174,
                selection_audit=_make_valid_audit(),
            )
        self.assertIn("R1_BUILD_FAIL", str(ctx.exception))


# ── RM-3: trigger_context 필수 필드 누락 → ValueError (failure path) ─────────

class TestRM3_MissingTriggerField(unittest.TestCase):
    def test_RM3_missing_trigger_field_raises_value_error(self):
        """trigger_context 필수 필드 누락 → ValueError (RULE-8 failure path)"""
        bad_trigger = {"trigger_reason": "X"}  # 나머지 필드 없음
        with self.assertRaises(ValueError) as ctx:
            build_recovery_package_r1(
                recovery_id="R",
                trigger_context=bad_trigger,
                selector_result=_make_valid_selector(),
                lkg_snapshot_payload=_make_valid_snapshot(),
                created_from_session=174,
                selection_audit=_make_valid_audit(),
            )
        self.assertIn("R1_BUILD_FAIL", str(ctx.exception))


# ── RM-4: validate_r1_package_integrity 정상 path ─────────────────────────

class TestRM4_ValidateIntegrityPass(unittest.TestCase):
    def test_RM4_valid_r1_passes_integrity(self):
        """유효한 r1 → validate_r1_package_integrity 예외 없음 (정상 path)"""
        r1 = _build_valid_r1()
        try:
            validate_r1_package_integrity(r1)
        except Exception as e:
            self.fail(f"validate_r1_package_integrity raised unexpectedly: {e}")


# ── RM-5: integrity_verdict 조작 → ValueError (failure path) ──────────────

class TestRM5_IntegrityVerdictTampered(unittest.TestCase):
    def test_RM5_tampered_verdict_raises_value_error(self):
        """integrity_verdict 조작 → ValueError (RULE-8 failure path)"""
        r1 = _build_valid_r1()
        r1["package_integrity"]["integrity_verdict"] = "TAMPERED"
        with self.assertRaises(ValueError) as ctx:
            validate_r1_package_integrity(r1)
        self.assertIn("R1_VALIDATION_FAIL", str(ctx.exception))


# ── RM-6: generate_recovery_candidate_r2 정상 path ────────────────────────

class TestRM6_GenerateR2Valid(unittest.TestCase):
    def test_RM6_valid_r2_returns_candidate_and_receipt(self):
        """유효한 r1 → r2 candidate + receipt 반환 (정상 path)"""
        r1 = _build_valid_r1()
        candidate, receipt = generate_recovery_candidate_r2(r1)
        self.assertIn("candidate_state_payload", candidate)
        self.assertEqual(candidate["generation_mode"], "LKG_STRICT_REPLAY")
        self.assertEqual(receipt["consistency_verdict"], "PASS")
        self.assertIn("receipt_integrity_hash", receipt)


# ── RM-7: recover_baseline → RecoveryError (failure path) ─────────────────

class TestRM7_RecoverBaseline(unittest.TestCase):
    def test_RM7_recover_baseline_raises_recovery_error(self):
        """recover_baseline 호출 → RecoveryError 즉시 발생 (RULE-8 failure path)"""
        with self.assertRaises(RecoveryError):
            recover_baseline()


if __name__ == "__main__":
    unittest.main()
