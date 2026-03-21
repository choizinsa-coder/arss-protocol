#!/usr/bin/env python3
"""
ARSS Generator v1.0
Canonical Schema v1.0 기준 구현
LOCK 날짜: 2026-03-21
"""

import hashlib
import json
import sys
from datetime import datetime, timezone


# ─────────────────────────────────────────
# 1. Canonicalization
# ─────────────────────────────────────────

def canonical_json(obj) -> str:
    """
    Canonical JSON 직렬화.
    규칙: 알파벳 오름차순 재귀 정렬 / UTF-8 / minified / null 금지 / 빈값 ""
    """
    if obj is None:
        raise ValueError("null 금지: None 값은 canonical_json 대상에 포함 불가")
    if isinstance(obj, dict):
        sorted_items = sorted(obj.items(), key=lambda x: x[0])
        inner = ",".join(
            f"{canonical_json(k)}:{canonical_json(v)}"
            for k, v in sorted_items
        )
        return "{" + inner + "}"
    if isinstance(obj, list):
        return "[" + ",".join(canonical_json(i) for i in obj) + "]"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return str(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    raise TypeError(f"지원하지 않는 타입: {type(obj)}")


# ─────────────────────────────────────────
# 2. Hash 계산
# ─────────────────────────────────────────

def compute_payload_hash(payload: dict) -> str:
    """payload_hash = SHA256(canonical_json(payload)) lowercase hex"""
    c = canonical_json(payload)
    return hashlib.sha256(c.encode("utf-8")).hexdigest()


def compute_chain_hash(prev_chain_hash: str, payload_hash: str) -> str:
    """
    genesis: chain_hash = SHA256("GENESIS:" + payload_hash)
    else:    chain_hash = SHA256(prev_chain_hash + ":" + payload_hash)
    입력 타입: hex string → UTF-8 encode → SHA256
    """
    if prev_chain_hash == "":
        raw = "GENESIS:" + payload_hash
    else:
        raw = prev_chain_hash + ":" + payload_hash
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────
# 3. HARD GUARD
# ─────────────────────────────────────────

def hard_guard(prev_chain_hash: str, payload_hash: str, chain_hash: str, payload: dict):
    """
    생성 차단 규칙 (HARD GUARD)
    조건 위반 시 ValueError 발생 → 생성/저장 금지
    """
    # 필수 필드 확인
    required_payload_fields = [
        "actor_id", "timestamp", "event_type",
        "governance_context", "sequence_label", "version"
    ]
    for f in required_payload_fields:
        if f not in payload or payload[f] == "" or payload[f] is None:
            raise ValueError(f"HARD GUARD FAIL: payload 필수 필드 누락 또는 빈값 → {f}")

    # prev_chain_hash 참조 실패 (genesis 제외)
    if prev_chain_hash is None:
        raise ValueError("HARD GUARD FAIL: prev_chain_hash 참조 실패")

    # prev == chain_hash (genesis 제외)
    if prev_chain_hash != "" and prev_chain_hash == chain_hash:
        raise ValueError("HARD GUARD FAIL: prev_chain_hash == chain_hash (체인 오류)")

    # payload_hash 재계산 일치 확인
    recalc = compute_payload_hash(payload)
    if recalc != payload_hash:
        raise ValueError(
            f"HARD GUARD FAIL: payload_hash 불일치\n"
            f"  계산값: {recalc}\n"
            f"  입력값: {payload_hash}"
        )


# ─────────────────────────────────────────
# 4. rpu_id 생성
# ─────────────────────────────────────────

def make_rpu_id(sequence: int) -> str:
    """RPU-000X 형식. 4자리 zero-padding."""
    return f"RPU-{sequence:04d}"


# ─────────────────────────────────────────
# 5. timestamp
# ─────────────────────────────────────────

def make_timestamp() -> str:
    """ISO8601 UTC 초 단위 (ms/μs 금지)"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────
# 6. Generator 메인
# ─────────────────────────────────────────

def generate_rpu(
    sequence: int,
    prev_chain_hash: str,
    payload_data: dict,
    output_binding: dict = None
) -> dict:
    """
    RPU 생성 메인 함수.

    Args:
        sequence: RPU 시퀀스 번호 (1, 2, 3 ...)
        prev_chain_hash: 직전 RPU의 chain_hash. genesis이면 "".
        payload_data: 사람이 입력하는 비즈니스 데이터 (메타 필드 포함)
        output_binding: hash 계산 제외 영역 (선택)

    Returns:
        완성된 RPU dict
    """
    # Step 1. rpu_id 생성
    rpu_id = make_rpu_id(sequence)

    # Step 2. payload 구성 (timestamp 자동 삽입 — payload에 없을 경우)
    payload = dict(payload_data)
    if "timestamp" not in payload or payload["timestamp"] == "":
        payload["timestamp"] = make_timestamp()

    # Step 3. payload_hash 계산
    payload_hash = compute_payload_hash(payload)

    # Step 4. chain_hash 계산
    chain_hash = compute_chain_hash(prev_chain_hash, payload_hash)

    # Step 5. HARD GUARD
    hard_guard(prev_chain_hash, payload_hash, chain_hash, payload)

    # Step 6. RPU 구성
    rpu = {
        "schema_version": "ARSS-RPU-1.0",
        "rpu_id": rpu_id,
        "payload": payload,
        "chain": {
            "prev_chain_hash": prev_chain_hash,
            "payload_hash": payload_hash,
            "chain_hash": chain_hash
        }
    }

    # Step 7. output_binding 삽입 (hash 계산 이후)
    if output_binding:
        rpu["output_binding"] = output_binding

    return rpu


# ─────────────────────────────────────────
# 7. Verifier
# ─────────────────────────────────────────

def verify_rpu(rpu: dict, expected_prev_chain_hash: str = None) -> dict:
    """
    RPU 독립 검증.
    Returns: {"status": "PASS"/"FAIL", "errors": [...]}
    """
    errors = []

    # 필수 top-level 필드
    for f in ["schema_version", "rpu_id", "payload", "chain"]:
        if f not in rpu:
            errors.append(f"필수 필드 누락: {f}")

    if errors:
        return {"status": "FAIL", "errors": errors}

    chain = rpu["chain"]
    payload = rpu["payload"]

    # payload_hash 재계산
    try:
        recalc_payload_hash = compute_payload_hash(payload)
        if recalc_payload_hash != chain.get("payload_hash", ""):
            errors.append(
                f"payload_hash 불일치\n"
                f"  기록: {chain.get('payload_hash')}\n"
                f"  재계산: {recalc_payload_hash}"
            )
    except Exception as e:
        errors.append(f"payload_hash 계산 오류: {e}")

    # chain_hash 재계산
    try:
        recalc_chain_hash = compute_chain_hash(
            chain.get("prev_chain_hash", ""),
            chain.get("payload_hash", "")
        )
        if recalc_chain_hash != chain.get("chain_hash", ""):
            errors.append(
                f"chain_hash 불일치\n"
                f"  기록: {chain.get('chain_hash')}\n"
                f"  재계산: {recalc_chain_hash}"
            )
    except Exception as e:
        errors.append(f"chain_hash 계산 오류: {e}")

    # prev_chain_hash 연속성 (외부 제공 시)
    if expected_prev_chain_hash is not None:
        if chain.get("prev_chain_hash") != expected_prev_chain_hash:
            errors.append(
                f"prev_chain_hash 불일치\n"
                f"  기록: {chain.get('prev_chain_hash')}\n"
                f"  예상: {expected_prev_chain_hash}"
            )

    # HARD GUARD: prev == chain_hash (genesis 제외)
    prev = chain.get("prev_chain_hash", "")
    ch = chain.get("chain_hash", "")
    if prev != "" and prev == ch:
        errors.append("HARD GUARD: prev_chain_hash == chain_hash")

    status = "PASS" if not errors else "FAIL"
    return {"status": status, "errors": errors}


# ─────────────────────────────────────────
# 8. 테스트 실행
# ─────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("ARSS Generator v1.0 — 자체 테스트")
    print("=" * 60)

    # ── 테스트 1: Genesis RPU 생성
    print("\n[ TEST 1: Genesis RPU 생성 ]")
    payload_1 = {
        "actor_id": "did:key:aiba-system-v1",
        "event_type": "EXECUTION",
        "governance_context": {
            "authority_root": "AIBA",
            "jurisdiction": "GLOBAL",
            "policy_id": "ARSS-PHASE1-RULES-v1.0"
        },
        "sequence_label": "RPU-0001",
        "version": "rpu/1.0",
        "timestamp": "2026-03-21T10:00:00Z",
        "event_name": "Generator v1.0 Test — Genesis"
    }

    rpu1 = generate_rpu(
        sequence=1,
        prev_chain_hash="",
        payload_data=payload_1
    )
    print(json.dumps(rpu1, indent=2, ensure_ascii=False))

    result1 = verify_rpu(rpu1, expected_prev_chain_hash="")
    print(f"\n검증 결과: {result1['status']}")
    if result1["errors"]:
        for e in result1["errors"]:
            print(f"  ❌ {e}")

    # ── 테스트 2: 연속 RPU 생성
    print("\n[ TEST 2: 연속 RPU 생성 ]")
    prev_hash = rpu1["chain"]["chain_hash"]

    payload_2 = {
        "actor_id": "did:key:aiba-system-v1",
        "event_type": "EXECUTION",
        "governance_context": {
            "authority_root": "AIBA",
            "jurisdiction": "GLOBAL",
            "policy_id": "ARSS-PHASE1-RULES-v1.0"
        },
        "sequence_label": "RPU-0002",
        "version": "rpu/1.0",
        "timestamp": "2026-03-21T10:01:00Z",
        "event_name": "Generator v1.0 Test — Chain Continuation"
    }

    rpu2 = generate_rpu(
        sequence=2,
        prev_chain_hash=prev_hash,
        payload_data=payload_2
    )
    print(json.dumps(rpu2, indent=2, ensure_ascii=False))

    result2 = verify_rpu(rpu2, expected_prev_chain_hash=prev_hash)
    print(f"\n검증 결과: {result2['status']}")
    if result2["errors"]:
        for e in result2["errors"]:
            print(f"  ❌ {e}")

    # ── 테스트 3: HARD GUARD 작동 확인
    print("\n[ TEST 3: HARD GUARD — prev == chain_hash 강제 발동 ]")
    fake_hash = "aabbcc" * 10 + "aabb"
    try:
        payload_bad = dict(payload_1)
        payload_bad["timestamp"] = "2026-03-21T10:02:00Z"
        payload_bad["sequence_label"] = "RPU-0003"
        payload_hash_bad = compute_payload_hash(payload_bad)
        # chain_hash를 prev_chain_hash와 동일하게 강제 설정 시도
        chain_hash_bad = compute_chain_hash(fake_hash, payload_hash_bad)
        hard_guard(fake_hash, payload_hash_bad, chain_hash_bad, payload_bad)
        print("  ❌ GUARD 미작동 (오류)")
    except ValueError as e:
        print(f"  ✅ GUARD 정상 작동: {e}")

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)
