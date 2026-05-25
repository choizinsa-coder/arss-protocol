import pytest
from tools.eps_v1_4.formatter import format_exploration, format_proposed, format_assertion

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
        "verifier_result": {"status": "PASS", "checked_at": datetime.now(timezone.utc).isoformat(), "ttl_sec": 30},
        "evidence_paths": ["evidence/receipts/VR-0043.json"],
    }
    r = format_assertion("완료되었습니다", ctx)
    assert "Evidence:" in r
    assert "Verifier:" in r
    assert "Receipt:" in r
    assert "VR-0043" in r
