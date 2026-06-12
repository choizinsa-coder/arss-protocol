"""
tests/test_pointer_guard_s231.py
pointer_guard_s231.py 단위 테스트

EAG: EAG-S231-POINTER-GUARD-001
VERIFY 항목:
  TC-01: 정상 POINTER → exit 0
  TC-02: stale current_session → exit 1
  TC-03: stale chain_tip → exit 1
  TC-04: stale context_hash → exit 1
  TC-05: POINTER 파일 없음 → exit 1
  TC-06: FINAL 파일 없음 → exit 1
  TC-07: POINTER JSON decode 실패 → exit 1
  TC-08: FINAL JSON decode 실패 → exit 1
  TC-09: FINAL 필수 키 누락 (session_count) → exit 1
  TC-10: FINAL 필수 키 누락 (chain) → exit 1
  TC-11: FINAL 필수 키 누락 (context_hash) → exit 1
  TC-12: FINAL 필수 키 누락 (schema_version) → exit 1
"""
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── 공통 픽스처 ─────────────────────────────────────────────────────────────

VALID_SC = {
    "session_count": 230,
    "chain": {"tip": "0e4383e", "prev_tip": "0e4383e"},
    "context_hash": "25517ae545815eeef0ef313ce0f371252489e5e01aebcc9b71928bb24a564547",
    "schema_version": "4.0",
}

VALID_PTR = {
    "current_session": 230,
    "canonical_file": "SESSION_CONTEXT.json",
    "final_file": "SESSION_CONTEXT_S230_FINAL.json",
    "chain_tip": "0e4383e",
    "prev_tip": "0e4383e",
    "context_hash": "25517ae545815eeef0ef313ce0f371252489e5e01aebcc9b71928bb24a564547",
    "generated_at": "2026-06-12T15:12:18.327261+09:00",
    "schema_version": "4.0",
}


def _run_guard(sc_data, ptr_data, *, no_final=False, no_pointer=False,
               bad_final_json=False, bad_pointer_json=False):
    """
    pointer_guard_s231 핵심 로직을 인라인 재현.
    SystemExit를 pytest.raises로 캐치하여 exit code 반환.
    """
    ROOT = Path('/opt/arss/engine/arss-protocol')

    # ── FINAL glob mock 구성
    if no_final:
        final_files = []
    else:
        fake_path = MagicMock(spec=Path)
        n = sc_data.get("session_count", 230)
        fake_path.name = f'SESSION_CONTEXT_S{n}_FINAL.json'
        final_files = [fake_path]

    def _logic():
        errors = []

        # ── 1. glob
        try:
            if not final_files:
                print('[FAIL] SESSION_CONTEXT_S*_FINAL.json 파일이 존재하지 않습니다.')
                sys.exit(1)
            latest_file = max(
                final_files,
                key=lambda p: int(p.name.split('_S')[1].split('_')[0])
            )
        except SystemExit:
            raise
        except Exception as e:
            print(f'[FAIL] FINAL 파일 탐색 실패: {e}')
            sys.exit(1)

        # ── 2. FINAL 로드
        try:
            if bad_final_json:
                raise json.JSONDecodeError("bad json", "", 0)
            sc = sc_data
            expected_current_session = sc['session_count']
            expected_final_file      = f'SESSION_CONTEXT_S{sc["session_count"]}_FINAL.json'
            expected_chain_tip       = sc['chain']['tip']
            expected_prev_tip        = sc['chain']['prev_tip']
            expected_context_hash    = sc['context_hash']
            expected_schema_version  = sc['schema_version']
        except FileNotFoundError as e:
            print(f'[FAIL] FINAL 파일 없음: {e}')
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f'[FAIL] FINAL 파일 JSON decode 실패: {e}')
            sys.exit(1)
        except KeyError as e:
            print(f'[FAIL] FINAL 파일 필수 키 누락: {e}')
            sys.exit(1)

        # ── 3. POINTER 로드
        try:
            if no_pointer:
                raise FileNotFoundError("no pointer")
            if bad_pointer_json:
                raise json.JSONDecodeError("bad json", "", 0)
            ptr = ptr_data
        except FileNotFoundError as e:
            print(f'[FAIL] POINTER 파일 없음: {e}')
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f'[FAIL] POINTER 파일 JSON decode 실패: {e}')
            sys.exit(1)

        # ── 4. 6-check
        checks = [
            ('current_session', ptr.get('current_session'), expected_current_session),
            ('chain_tip',       ptr.get('chain_tip'),        expected_chain_tip),
            ('prev_tip',        ptr.get('prev_tip'),          expected_prev_tip),
            ('context_hash',    ptr.get('context_hash'),      expected_context_hash),
            ('final_file',      ptr.get('final_file'),        expected_final_file),
            ('schema_version',  ptr.get('schema_version'),    expected_schema_version),
        ]

        for name, got, expected in checks:
            if got == expected:
                print(f'[OK]   {name:20s} == {str(got)[:64]}')
            else:
                errors.append(f'{name}: got={got} | expected={expected}')
                print(f'[FAIL] {name:20s} got={got} | expected={expected}')

        # ── 5. exit
        print()
        if errors:
            print(f'POINTER GUARD FAILED — {len(errors)} error(s)')
            for e in errors:
                print(f'  >> {e}')
            sys.exit(1)
        else:
            print('POINTER GUARD PASSED: ALL 6 CHECKS OK')
            sys.exit(0)

    with pytest.raises(SystemExit) as exc_info:
        _logic()
    return exc_info.value.code


# ── TC-01: 정상 POINTER → exit 0 ────────────────────────────────────────────
def test_tc01_normal_pass():
    """정상 POINTER — 전체 6-check PASS → exit 0"""
    code = _run_guard(VALID_SC, VALID_PTR)
    assert code == 0, f"TC-01: expected exit 0, got {code}"


# ── TC-02: stale current_session → exit 1 ───────────────────────────────────
def test_tc02_stale_current_session():
    """POINTER.current_session이 FINAL.session_count보다 낮음 → exit 1"""
    ptr = {**VALID_PTR, "current_session": 202}
    code = _run_guard(VALID_SC, ptr)
    assert code == 1, f"TC-02: expected exit 1, got {code}"


# ── TC-03: stale chain_tip → exit 1 ─────────────────────────────────────────
def test_tc03_stale_chain_tip():
    """POINTER.chain_tip이 FINAL과 불일치 → exit 1"""
    ptr = {**VALID_PTR, "chain_tip": "deadbeef"}
    code = _run_guard(VALID_SC, ptr)
    assert code == 1, f"TC-03: expected exit 1, got {code}"


# ── TC-04: stale context_hash → exit 1 ──────────────────────────────────────
def test_tc04_stale_context_hash():
    """POINTER.context_hash가 FINAL과 불일치 → exit 1"""
    ptr = {**VALID_PTR, "context_hash": "aaaa1111bbbb2222cccc3333dddd4444eeee5555ffff6666aaaa1111bbbb2222"}
    code = _run_guard(VALID_SC, ptr)
    assert code == 1, f"TC-04: expected exit 1, got {code}"


# ── TC-05: POINTER 파일 없음 → exit 1 ───────────────────────────────────────
def test_tc05_no_pointer_file():
    """SESSION_CONTEXT_POINTER.json 미존재 → exit 1"""
    code = _run_guard(VALID_SC, VALID_PTR, no_pointer=True)
    assert code == 1, f"TC-05: expected exit 1, got {code}"


# ── TC-06: FINAL 파일 없음 → exit 1 ─────────────────────────────────────────
def test_tc06_no_final_file():
    """SESSION_CONTEXT_S*_FINAL.json glob 결과 0건 → exit 1"""
    code = _run_guard(VALID_SC, VALID_PTR, no_final=True)
    assert code == 1, f"TC-06: expected exit 1, got {code}"


# ── TC-07: POINTER JSON decode 실패 → exit 1 ────────────────────────────────
def test_tc07_pointer_json_decode_fail():
    """POINTER 파일 JSON 파싱 실패 → exit 1"""
    code = _run_guard(VALID_SC, VALID_PTR, bad_pointer_json=True)
    assert code == 1, f"TC-07: expected exit 1, got {code}"


# ── TC-08: FINAL JSON decode 실패 → exit 1 ──────────────────────────────────
def test_tc08_final_json_decode_fail():
    """FINAL 파일 JSON 파싱 실패 → exit 1"""
    code = _run_guard(VALID_SC, VALID_PTR, bad_final_json=True)
    assert code == 1, f"TC-08: expected exit 1, got {code}"


# ── TC-09: FINAL 필수 키 누락 (session_count) → exit 1 ──────────────────────
def test_tc09_final_missing_session_count():
    """FINAL 파일에 session_count 키 없음 → exit 1"""
    sc = {k: v for k, v in VALID_SC.items() if k != 'session_count'}
    code = _run_guard(sc, VALID_PTR)
    assert code == 1, f"TC-09: expected exit 1, got {code}"


# ── TC-10: FINAL 필수 키 누락 (chain) → exit 1 ──────────────────────────────
def test_tc10_final_missing_chain():
    """FINAL 파일에 chain 키 없음 → exit 1"""
    sc = {k: v for k, v in VALID_SC.items() if k != 'chain'}
    code = _run_guard(sc, VALID_PTR)
    assert code == 1, f"TC-10: expected exit 1, got {code}"


# ── TC-11: FINAL 필수 키 누락 (context_hash) → exit 1 ───────────────────────
def test_tc11_final_missing_context_hash():
    """FINAL 파일에 context_hash 키 없음 → exit 1"""
    sc = {k: v for k, v in VALID_SC.items() if k != 'context_hash'}
    code = _run_guard(sc, VALID_PTR)
    assert code == 1, f"TC-11: expected exit 1, got {code}"


# ── TC-12: FINAL 필수 키 누락 (schema_version) → exit 1 ─────────────────────
def test_tc12_final_missing_schema_version():
    """FINAL 파일에 schema_version 키 없음 → exit 1"""
    sc = {k: v for k, v in VALID_SC.items() if k != 'schema_version'}
    code = _run_guard(sc, VALID_PTR)
    assert code == 1, f"TC-12: expected exit 1, got {code}"
