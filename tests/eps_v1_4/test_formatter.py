import pytest
from tools.eps_v1_4.formatter import format_exploration, format_proposed, format_assertion


# ── 기존 테스트 ────────────────────────────────────────────────
def test_format_e():
    r = format_exploration("가능성이 있습니다")
    assert r.startswith("[E]")
    assert "가능성" in r


def test_format_p():
    r = format_proposed("다음 단계로 수정 제안합니다\nNext Action: 패키지 작성")
    assert r.startswith("[P]")


def test_format_a():
    from datetime import datetime, timezone
    ctx = {
        "receipt": {"receipt_id": "VR-0043"},
        "verifier_result": {
            "status": "PASS",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "ttl_sec": 30,
        },
        "evidence_paths": ["evidence/receipts/VR-0043.json"],
    }
    r = format_assertion("완료되었습니다", ctx)
    assert "Evidence:" in r
    assert "Verifier:" in r
    assert "Receipt:" in r
    assert "VR-0043" in r


# ── failure path ───────────────────────────────────────────────
def test_format_e_empty_string():
    """빈 문자열 입력 — [E] 접두사 유지, strip 적용"""
    r = format_exploration("")
    assert r.startswith("[E]")


def test_format_assertion_empty_context():
    """빈 context — receipt_id/verifier_status UNKNOWN, evidence NONE 폴백"""
    r = format_assertion("완료되었습니다", {})
    assert "UNKNOWN" in r
    assert "NONE" in r


def test_format_assertion_none_receipt():
    """receipt=None — receipt_id UNKNOWN 폴백"""
    r = format_assertion("완료되었습니다", {"receipt": None})
    assert "UNKNOWN" in r


def test_format_assertion_none_verifier():
    """verifier_result=None — verifier_status UNKNOWN 폴백"""
    r = format_assertion(
        "완료되었습니다",
        {"verifier_result": None, "receipt": {"receipt_id": "R-001"}},
    )
    assert "UNKNOWN" in r


def test_format_assertion_empty_evidence_paths():
    """evidence_paths=[] — evidence_str NONE 폴백"""
    r = format_assertion("완료되었습니다", {"evidence_paths": []})
    assert "NONE" in r
