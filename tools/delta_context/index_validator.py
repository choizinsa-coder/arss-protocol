ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
index_validator.py
==================
DOMAIN_INDEX 무결성 검증 전용 모듈

설계 기준: 도미 [DESIGN] index_validator.py (S65 EAG 승인)
계층: READ-ONLY / FAIL-CLOSED
호출 위치: BOOT 직후 → auto_loader.run() 시작부 (INDEX_INTEGRITY_SHADOW_CHECK)

검증 4축:
  G1. Sequence Continuity       — delta sequence_number 연속성
  G2. latest_delta_id           — INDEX 헤더 vs 실제 마지막 delta
  G3. latest_content_hash       — INDEX 헤더 vs 실제 마지막 delta
  G4. delta_count               — INDEX 기록값 vs 실제 개수

HARD CONSTRAINTS:
  - write 금지 (READ ONLY)
  - atomic_sync 호출 금지
  - mutation_gate 호출 금지
  - side-effect 없음
  - 자동 복구 금지
  - FAIL 시 hard_stop: True 반환 (FAIL-CLOSED)

승인: 비오(Joshua) EAG — S65
"""


import json
import os
import sys
from typing import Any


# ---------------------------------------------------------------------------
# 반환 헬퍼
# ---------------------------------------------------------------------------

def _pass() -> dict:
    return {"result": "PASS"}


def _fail(reason: str) -> dict:
    return {"result": "FAIL", "reason": reason, "hard_stop": True}


# ---------------------------------------------------------------------------
# 내부 로딩 유틸
# ---------------------------------------------------------------------------

def _load_json(path: str, label: str) -> tuple[Any, dict | None]:
    """
    JSON 파일을 로드한다.
    성공 시 (data, None), 실패 시 (None, fail_dict) 반환.
    """
    if not os.path.exists(path):
        return None, _fail(f"{label} 파일 미존재: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data, None
    except json.JSONDecodeError as exc:
        return None, _fail(f"{label} JSON 파싱 실패 ({path}): {exc}")
    except OSError as exc:
        return None, _fail(f"{label} 접근 실패 ({path}): {exc}")


# ---------------------------------------------------------------------------
# 도메인별 검증 — 내부 서브루틴 (RULE-5 분리, EAG-A1, S156)
# ---------------------------------------------------------------------------

def _validate_index_fields(
    domain: str,
    domain_entry: dict,
) -> tuple[dict | None, str, str, int]:
    """
    INDEX 필수 필드 존재 검증 및 변수 추출.
    PASS 시 (None, id, hash, count), FAIL 시 (fail_dict, '', '', 0) 반환.
    """
    required_fields = ["latest_delta_id", "latest_content_hash", "delta_count"]
    for field in required_fields:
        if field not in domain_entry:
            return (
                _fail(f"[G4-구조] domain='{domain}' INDEX 필수 필드 누락: '{field}'"),
                "", "", 0,
            )
    return (
        None,
        domain_entry["latest_delta_id"],
        domain_entry["latest_content_hash"],
        domain_entry["delta_count"],
    )


def _load_domain_deltas(
    domain: str,
    delta_dir: str,
    index_delta_count: int,
) -> tuple[dict | None, list]:
    """
    delta_dir에서 delta JSON 파일을 로드하고 sequence_number 기준 정렬.
    반환:
      (pass_dict, [])      — empty domain PASS
      (fail_dict, [])      — FAIL
      (None, [delta, ...]) — 정상 로드 완료
    """
    if not os.path.isdir(delta_dir):
        if index_delta_count == 0:
            print(f"  [G-PASS] domain='{domain}' — empty domain (delta_count=0), PASS")
            return _pass(), []
        return _fail(
            f"[G-DIR] domain='{domain}' DELTA_LOG 디렉터리 미존재: {delta_dir}"
        ), []

    try:
        filenames = sorted(
            f for f in os.listdir(delta_dir) if f.endswith(".json")
        )
    except OSError as exc:
        return _fail(
            f"[G-DIR] domain='{domain}' DELTA_LOG 디렉터리 접근 실패: {exc}"
        ), []

    if not filenames and index_delta_count == 0:
        print(f"  [G-PASS] domain='{domain}' — empty domain (no files, delta_count=0), PASS")
        return _pass(), []

    if not filenames and index_delta_count != 0:
        return _fail(
            f"[G4] domain='{domain}' delta 파일 없음이나 INDEX.delta_count={index_delta_count}"
        ), []

    deltas: list[dict] = []
    for fname in filenames:
        fpath = os.path.join(delta_dir, fname)
        data, err = _load_json(fpath, f"delta({fname})")
        if err:
            return err, []
        deltas.append(data)

    try:
        deltas.sort(key=lambda d: int(d["sequence_number"]))
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(
            f"[G1] domain='{domain}' sequence_number 필드 파싱 실패: {exc}"
        ), []

    return None, deltas


def _validate_delta_sequence(
    domain: str,
    deltas: list[dict],
    index_delta_count: int,
) -> dict | None:
    """
    G4 delta_count 정합성 + G1 sequence_number 연속성 검증.
    PASS 시 None, FAIL 시 fail_dict 반환.
    """
    actual_count = len(deltas)
    if actual_count != index_delta_count:
        return _fail(
            f"[G4] domain='{domain}' delta_count 불일치: "
            f"INDEX={index_delta_count}, 실제={actual_count}"
        )
    print(f"  [G4-PASS] domain='{domain}' delta_count={actual_count}")

    seq_numbers: list[int] = []
    for d in deltas:
        try:
            seq_numbers.append(int(d["sequence_number"]))
        except (KeyError, TypeError, ValueError) as exc:
            return _fail(
                f"[G1] domain='{domain}' sequence_number 읽기 실패: {exc}"
            )

    expected = list(range(1, actual_count + 1))
    if seq_numbers != expected:
        if len(seq_numbers) != len(set(seq_numbers)):
            return _fail(
                f"[G1] domain='{domain}' sequence_number 중복 발견: {seq_numbers}"
            )
        return _fail(
            f"[G1] domain='{domain}' sequence_number 연속성 위반: "
            f"기대={expected}, 실제={seq_numbers}"
        )
    print(f"  [G1-PASS] domain='{domain}' sequence continuity OK (1~{actual_count})")
    return None


def _validate_delta_integrity(
    domain: str,
    last_delta: dict,
    index_latest_delta_id: str,
    index_latest_content_hash: str,
) -> dict | None:
    """
    G2 latest_delta_id + G3 latest_content_hash 정합성 검증.
    PASS 시 None, FAIL 시 fail_dict 반환.
    """
    try:
        actual_last_delta_id: str = last_delta["delta_id"]
    except KeyError:
        return _fail(
            f"[G2] domain='{domain}' 마지막 delta에 'delta_id' 필드 없음"
        )

    if actual_last_delta_id != index_latest_delta_id:
        return _fail(
            f"[G2] domain='{domain}' latest_delta_id 불일치: "
            f"INDEX='{index_latest_delta_id}', 실제='{actual_last_delta_id}'"
        )
    print(f"  [G2-PASS] domain='{domain}' latest_delta_id='{actual_last_delta_id}'")

    try:
        actual_last_content_hash: str = last_delta["content_hash"]
    except KeyError:
        return _fail(
            f"[G3] domain='{domain}' 마지막 delta에 'content_hash' 필드 없음"
        )

    if actual_last_content_hash != index_latest_content_hash:
        return _fail(
            f"[G3] domain='{domain}' latest_content_hash 불일치: "
            f"INDEX='{index_latest_content_hash}', 실제='{actual_last_content_hash}'"
        )
    print(f"  [G3-PASS] domain='{domain}' latest_content_hash='{actual_last_content_hash[:16]}...'")
    return None


# ---------------------------------------------------------------------------
# 도메인별 검증 — 공개 진입점
# ---------------------------------------------------------------------------

def _validate_domain(
    domain: str,
    domain_entry: dict,
    delta_root: str,
) -> dict:
    """
    단일 domain에 대해 G1~G4 검증을 수행한다.
    FAIL 즉시 반환 (fail-fast).
    """
    # G_FIELDS: INDEX 필수 필드 검증
    err, index_latest_delta_id, index_latest_content_hash, index_delta_count = \
        _validate_index_fields(domain, domain_entry)
    if err:
        return err

    # G_LOAD: delta 파일 로드
    delta_dir = os.path.join(delta_root, domain)
    result, deltas = _load_domain_deltas(domain, delta_dir, index_delta_count)
    if result is not None:
        return result

    # G_SEQ: G4 count + G1 sequence 연속성
    err = _validate_delta_sequence(domain, deltas, index_delta_count)
    if err:
        return err

    # G_INTEG: G2 delta_id + G3 content_hash
    err = _validate_delta_integrity(
        domain, deltas[-1], index_latest_delta_id, index_latest_content_hash
    )
    if err:
        return err

    return _pass()


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

def validate_index(index_path: str, delta_root: str) -> dict:
    """
    DOMAIN_INDEX 전체 무결성 검증.

    Parameters
    ----------
    index_path : str
        INDEX.json 파일 경로
    delta_root : str
        domain별 DELTA_LOG가 저장된 루트 디렉터리
        (예: /opt/arss/engine/arss-protocol/delta_context/DELTA_LOG/)

    Returns
    -------
    dict
        PASS: {"result": "PASS"}
        FAIL: {"result": "FAIL", "reason": str, "hard_stop": True}
    """

    print("[INDEX_INTEGRITY_SHADOW_CHECK] 시작")
    print(f"  index_path : {index_path}")
    print(f"  delta_root : {delta_root}")

    # ── INDEX.json 로드 ──────────────────────────────────────────────────
    index_data, err = _load_json(index_path, "INDEX.json")
    if err:
        print(f"[INDEX_INTEGRITY_SHADOW_CHECK] FAIL — {err['reason']}")
        return err

    # ── INDEX 최상위 구조 확인 ───────────────────────────────────────────
    if not isinstance(index_data, dict):
        reason = "INDEX.json 최상위가 dict가 아님"
        print(f"[INDEX_INTEGRITY_SHADOW_CHECK] FAIL — {reason}")
        return _fail(reason)

    domains_section = index_data.get("domains")
    if domains_section is None:
        reason = "INDEX.json 'domains' 키 누락"
        print(f"[INDEX_INTEGRITY_SHADOW_CHECK] FAIL — {reason}")
        return _fail(reason)

    if not isinstance(domains_section, dict):
        reason = "INDEX.json 'domains' 값이 dict가 아님"
        print(f"[INDEX_INTEGRITY_SHADOW_CHECK] FAIL — {reason}")
        return _fail(reason)

    # ── domain 없음(빈 INDEX) — PASS 허용 ───────────────────────────────
    if not domains_section:
        print("[INDEX_INTEGRITY_SHADOW_CHECK] domain 없음 — PASS (빈 INDEX)")
        return _pass()

    # ── domain별 순회 검증 ───────────────────────────────────────────────
    for domain, domain_entry in domains_section.items():
        print(f"\n[DOMAIN] '{domain}' 검증 시작")

        if not isinstance(domain_entry, dict):
            reason = f"domain='{domain}' 항목이 dict가 아님"
            print(f"[INDEX_INTEGRITY_SHADOW_CHECK] FAIL — {reason}")
            return _fail(reason)

        result = _validate_domain(domain, domain_entry, delta_root)
        if result["result"] == "FAIL":
            print(f"[INDEX_INTEGRITY_SHADOW_CHECK] FAIL — {result['reason']}")
            return result

    print("\n[INDEX_INTEGRITY_SHADOW_CHECK] 전체 PASS")
    return _pass()
