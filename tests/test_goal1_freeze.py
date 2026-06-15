"""
test_goal1_freeze.py
Goal 1 핵심 산출물 불변성 검증 (Freeze Guard)

Freeze Version : G1-FRZ-001
EAG            : EAG-S239-GOAL1-FREEZE-001
근거 문서       : GOAL1_FREEZE_RECORD.md
생성 세션       : S239
생성자          : 캐디 (COO)
v2 확장 세션    : S239 (도미 RAW 관측 지적 반영 — 전체 Freeze 범위 적용)

== 목적 ==
Goal 2 진행 중 Goal 1 핵심 산출물이 무단 변경되면 즉시 pytest FAIL.
캐디/도미의 실수 또는 컨텍스트 누락으로 인한 훼손을 자동 차단한다.

== 변경 금지 ==
FROZEN_HASHES / FROZEN_JOURNAL_HASH 값은 비오님 EAG 승인 없이 절대 수정 불가.
hash 갱신이 필요한 경우: 별도 EAG + 도미 설계 + 제니 검증 필수.

== Freeze 수준 구분 ==
완전 동결: docs/goal1_metrics_framework_v1.0.md
           context/governance/rules.json
           GOAL1_FREEZE_RECORD.md
           tools/ledger/ (3종)
조건부:    tools/guard/pointer_guard_s231.py      (버그픽스 EAG 하 허용)
           tools/close/session_close_generator.py (버그픽스 EAG 하 허용)
WORM 특례: session_journal.jsonl — append-only이므로 전체 hash 고정 불가.
           last_entry_hash만 고정 (S239 기준).
"""

import hashlib
import json
import os
import pytest

# ── 완전 동결 / 조건부 동결 파일 hash (VPS 실측, S239) ────────────────
FROZEN_HASHES = {
    # 완전 동결
    "docs/goal1_metrics_framework_v1.0.md":
        "97442eec4a59de39c37d23fd5eea0373abd4d8fab8a6bea4f5076cefecb5f079",
    "context/governance/rules.json":
        "c3229b840d7199fa6d2c2cddc1b4c10585b9911bb6a6d16d481adc9aa065c6a1",
    "GOAL1_FREEZE_RECORD.md":
        "094d8ccdd0f468dd4a37394303d84fa86925a25a6ab199daaf0d587a10e23cf2",
    "tools/ledger/ledger_writer.py":
        "16ece7b4523e8a97b116c0888c4ce8401b31f61dffc169686a5b5b1b56adc168",
    "tools/ledger/ledger_verifier.py":
        "75363c2594c0c1fb3440cf480c777f317b0a1553489a776dd600b965a0eceaa4",
    "tools/ledger/observation_verifier.py":
        "f754137f761edd131921bc1c4c754ec5452d181e1dc92cbec2c2b12dfb3e228b",
    # 조건부 동결 (버그픽스 EAG 하 허용 — hash 갱신 시 EAG 필수)
    "tools/guard/pointer_guard_s231.py":
        "3e25cf94bf0bf13635aa7f9675aafffb88927e6ecc5ccf3581e6639effd0c9c0",
    "tools/close/session_close_generator.py":
        "6d4422c1d7dd77ad2f20de5109067d599b50ab398e9cd4eb19075c43058de028",
}

# ── WORM 특례: session_journal last_entry_hash 고정 (S239 기준) ─────────
# append-only이므로 전체 hash 고정 불가. last_entry_hash만 검증.
# journal에 새 entry가 append되면 이 값도 함께 EAG 하 갱신 필요.
FROZEN_JOURNAL_LAST_ENTRY_HASH = (
    "8b9a2ecfa9c189918c2a16381dfc6e38504ec93d06b0045dacf0df7a6ad340fe"
)
JOURNAL_PATH = "session_journal/session_journal.jsonl"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── TC-01~08: 파일 hash 검증 ─────────────────────────────────────────
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


# ── TC-09: journal last_entry_hash 검증 (WORM 특례) ──────────────────
def test_goal1_journal_last_entry_hash():
    """
    session_journal.jsonl은 append-only WORM.
    전체 hash 고정 불가 — last_entry_hash만 고정.
    새 entry append 시 이 값도 EAG 하 갱신 필요.
    """
    abs_path = os.path.join(ROOT, JOURNAL_PATH)

    assert os.path.exists(abs_path), (
        f"[FREEZE VIOLATION] session_journal.jsonl 없음.\n"
        f"WORM 장부가 삭제되었습니다. 즉시 복구 필요."
    )

    last_entry = None
    with open(abs_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last_entry = json.loads(line)

    assert last_entry is not None, (
        "[FREEZE VIOLATION] session_journal.jsonl이 비어 있습니다."
    )

    actual = last_entry.get("entry_hash", "")
    assert actual == FROZEN_JOURNAL_LAST_ENTRY_HASH, (
        f"[FREEZE VIOLATION] journal last_entry_hash 불일치\n"
        f"  expected : {FROZEN_JOURNAL_LAST_ENTRY_HASH}\n"
        f"  actual   : {actual}\n"
        f"journal에 무단 append 또는 변조가 발생했을 수 있습니다.\n"
        f"비오님께 즉시 보고하십시오."
    )
