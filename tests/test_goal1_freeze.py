"""
test_goal1_freeze.py
Goal 1 핵심 산출물 불변성 검증 (Freeze Guard)

Freeze Version : G1-FRZ-001
EAG            : EAG-S239-GOAL1-FREEZE-001 (예정)
근거 문서       : GOAL1_FREEZE_RECORD.md
생성 세션       : S239
생성자          : 캐디 (COO)

== 목적 ==
Goal 2 진행 중 Goal 1 핵심 산출물이 무단 변경되면 즉시 pytest FAIL.
캐디/도미의 실수 또는 컨텍스트 누락으로 인한 훼손을 자동 차단한다.

== 변경 금지 ==
FROZEN_HASHES 값은 비오님 EAG 승인 없이 절대 수정 불가.
hash 갱신이 필요한 경우: 별도 EAG + 도미 설계 + 제니 검증 필수.
"""

import hashlib
import os
import pytest

# ── Freeze 기준 (VPS 실측, S239) ─────────────────────────────────────
FROZEN_HASHES = {
    "docs/goal1_metrics_framework_v1.0.md":
        "97442eec4a59de39c37d23fd5eea0373abd4d8fab8a6bea4f5076cefecb5f079",
    "context/governance/rules.json":
        "c3229b840d7199fa6d2c2cddc1b4c10585b9911bb6a6d16d481adc9aa065c6a1",
    "GOAL1_FREEZE_RECORD.md":
        "4d97e2b5cacf0ade6ed99d7097927d6cd26177c819bf316924de2c3d0b740602",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.mark.parametrize("rel_path,expected_hash", FROZEN_HASHES.items())
def test_goal1_frozen_file_integrity(rel_path: str, expected_hash: str):
    """
    Goal 1 Freeze Guard — G1-FRZ-001
    핵심 산출물이 변조되면 즉시 FAIL.
    hash 갱신은 비오님 EAG 승인 없이 불가.
    """
    abs_path = os.path.join(ROOT, rel_path)

    assert os.path.exists(abs_path), (
        f"[FREEZE VIOLATION] 파일 없음: {rel_path}\n"
        f"Goal 1 핵심 산출물이 삭제되었습니다. 즉시 복구 필요."
    )

    actual = _sha256(abs_path)
    assert actual == expected_hash, (
        f"[FREEZE VIOLATION] hash 불일치: {rel_path}\n"
        f"  expected : {expected_hash}\n"
        f"  actual   : {actual}\n"
        f"변경 이력 확인 후 비오님께 즉시 보고하십시오.\n"
        f"복구 절차: GOAL1_FREEZE_RECORD.md 'Freeze 위반 시 복구 기준' 참조."
    )
