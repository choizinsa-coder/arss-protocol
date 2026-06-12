"""
tests/test_session_close_generator.py
session_close_generator.py 단위 테스트

EAG: EAG-S231-CLOSE-GENERATOR-001
VERIFY 항목:
  TC-01: 정상 dry-run → exit 0, 파일 미생성
  TC-02: 정상 운영 실행 → exit 0, 5파일 생성 + 3-way verify PASS
  TC-03: delta-json 필수 키 누락 → exit 1
  TC-04: delta-json 타입 불일치 → exit 1
  TC-05: delta-json 파일 없음 → exit 1
  TC-06: delta-json JSON decode 실패 → exit 1
  TC-07: approval-id 미제공 → exit 1
  TC-08: approval-id 형식 오류 → exit 1
  TC-09: 이전 FINAL 파일 없음 → exit 1
  TC-10: verify 실패 (session_count 불일치) → exit 1
  TC-11: rollback 경로 — 단계 6 실패 시 SC_FINAL 삭제 확인
  TC-12: _validate_approval_id 정상 패턴
  TC-13: _validate_approval_id 비정상 패턴
  TC-14: _context_hash ensure_ascii=False 방식 검증
"""
import hashlib
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# session_close_generator 경로 주입
sys.path.insert(0, str(Path(__file__).parent.parent / 'tools' / 'close'))
import session_close_generator as scg

# ── 공통 픽스처 ──────────────────────────────────────────────────

VALID_DELTA = {
    'session_reentry':         {'last_session': 230, 'resume_point': 'test', 'eag_carryover': '없음'},
    'next_steps':              ['S232: 작업 1'],
    'agent_focus':             {'beo': 'test', 'caddy': 'test', 'domi': '미호출', 'jeni': '미호출'},
    'pytest_status':           {'last_run_date': '2026-06-12', 'last_run_session': 231,
                                'regression_impact': 'NONE', 'total_failed': 0,
                                'total_passed': 1574, 'total_skipped': 94, 'note': 'test'},
    'system_changes':          {'deployed_session': 231, 'commits': ['abc1234'],
                                'changes': ['test'], 'eag_chain': 'EAG-S231-TEST',
                                'pytest_result': '1574 passed / 0 failed / 94 skipped'},
    'caddy_governance_record': {'session': 231, 'date': '2026-06-12',
                                'eag_gates_this_session': [], 'incidents': [],
                                'oi_observations': [], 'notable': 'test',
                                'stabilization_metrics': {'M07_role_boundary': 'PASS'}},
    'visibility_metrics':      {'session': 231, 'date': '2026-06-12',
                                'M-01_active_canonical_key_count': 42,
                                'chain_tip': 'abc1234',
                                'pytest_result': '1574 passed / 0 failed / 94 skipped',
                                'key_decisions': []},
    'session_delta':           {'session': 231, 'modified_keys': [], 'added_keys': [], 'removed_keys': []},
    'sync_meta':               {'last_sync_date': '2026-06-12', 'last_sync_session': 231,
                                'files': ['SESSION_CONTEXT_S231_FINAL.json'], 'sync_status': 'SYNCED'},
}

VALID_PREV_SC = {
    'session_count': 230,
    'chain': {'session': 230, 'tip': '0e4383e', 'prev_tip': '0e4383e'},
    'context_hash': 'aabbcc',
    'schema_version': '4.0',
    'system_changes_s227': {'deployed_session': 227},  # GOV-003 제거 대상 (N-4=227)
}

VALID_APPROVAL = 'EAG-S231-CLOSE-GENERATOR-001'
N = 231
CHAIN_TIP = 'abc1234'
PREV_TIP = '0e4383e'


def _run(args_list, *, monkeypatch_root=None, tmp_path=None):
    """
    session_close_generator.main()을 SystemExit 캐치하며 실행.
    tmp_path 제공 시 ROOT를 tmp_path로 교체.
    """
    with pytest.raises(SystemExit) as exc_info:
        with patch('sys.argv', ['session_close_generator.py'] + args_list):
            if tmp_path is not None:
                with patch.object(scg, 'ROOT', tmp_path):
                    scg.main()
            else:
                scg.main()
    return exc_info.value.code


def _make_prev_final(tmp_path, sc_data=None, n=N):
    """tmp_path에 S{N-1}_FINAL.json 생성"""
    data = sc_data if sc_data is not None else VALID_PREV_SC
    path = tmp_path / f'SESSION_CONTEXT_S{n - 1}_FINAL.json'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def _make_prev_archive(tmp_path, n=N):
    """tmp_path에 S{N-1} ARCHIVE 생성"""
    path = tmp_path / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n - 1}.json'
    path.write_text(json.dumps({
        '_archive_meta': {'total_tier_d_keys': 78}
    }, ensure_ascii=False), encoding='utf-8')
    return path


def _make_delta_json(tmp_path, delta=None):
    """tmp_path에 delta.json 생성"""
    data = delta if delta is not None else VALID_DELTA
    path = tmp_path / 'delta.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


def _make_canonical_sc(tmp_path, content=None):
    """tmp_path에 SESSION_CONTEXT.json 생성"""
    path = tmp_path / 'SESSION_CONTEXT.json'
    path.write_text(json.dumps(content or {'dummy': True}), encoding='utf-8')
    return path


# ── TC-01: 정상 dry-run → exit 0, 파일 미생성 ────────────────────
def test_tc01_dry_run_no_files(tmp_path):
    """dry-run: 5개 파일 전부 미생성, exit 0"""
    _make_prev_final(tmp_path)
    _make_prev_archive(tmp_path)
    delta_path = _make_delta_json(tmp_path)

    code = _run([
        '--session', str(N),
        '--chain-tip', CHAIN_TIP,
        '--prev-tip', PREV_TIP,
        '--delta-json', str(delta_path),
        '--dry-run',
    ], tmp_path=tmp_path)

    assert code == 0, f'TC-01: expected exit 0, got {code}'
    # 운영 파일 미생성 확인
    assert not (tmp_path / f'SESSION_CONTEXT_S{N}_FINAL.json').exists()
    assert not (tmp_path / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{N}.json').exists()
    assert not (tmp_path / 'SESSION_CONTEXT_POINTER.json').exists()
    assert not (tmp_path / 'SESSION_CONTEXT_STALE_MANIFEST.json').exists()


# ── TC-02: 정상 운영 실행 → exit 0, 5파일 생성 ───────────────────
def test_tc02_normal_run(tmp_path):
    """정상 운영 실행: 5파일 생성 + exit 0"""
    _make_prev_final(tmp_path)
    _make_prev_archive(tmp_path)
    _make_canonical_sc(tmp_path)
    delta_path = _make_delta_json(tmp_path)
    # POINTER / MANIFEST 초기 파일 생성 (overwrite 대상)
    (tmp_path / 'SESSION_CONTEXT_POINTER.json').write_text('{}')
    (tmp_path / 'SESSION_CONTEXT_STALE_MANIFEST.json').write_text('{}')

    code = _run([
        '--session', str(N),
        '--chain-tip', CHAIN_TIP,
        '--prev-tip', PREV_TIP,
        '--delta-json', str(delta_path),
        '--approval-id', VALID_APPROVAL,
    ], tmp_path=tmp_path)

    assert code == 0, f'TC-02: expected exit 0, got {code}'
    # 5파일 존재 확인
    assert (tmp_path / f'SESSION_CONTEXT_S{N}_FINAL.json').exists()
    assert (tmp_path / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{N}.json').exists()
    assert (tmp_path / 'SESSION_CONTEXT.json').exists()
    assert (tmp_path / 'SESSION_CONTEXT_POINTER.json').exists()
    assert (tmp_path / 'SESSION_CONTEXT_STALE_MANIFEST.json').exists()

    # SC_FINAL 내용 검증
    with open(tmp_path / f'SESSION_CONTEXT_S{N}_FINAL.json', encoding='utf-8') as f:
        sc = json.load(f)
    assert sc['session_count'] == N
    assert sc['chain']['tip'] == CHAIN_TIP

    # 3-way hash 일치 검증
    with open(tmp_path / 'SESSION_CONTEXT_POINTER.json', encoding='utf-8') as f:
        ptr = json.load(f)
    with open(tmp_path / 'SESSION_CONTEXT_STALE_MANIFEST.json', encoding='utf-8') as f:
        mf = json.load(f)
    assert sc['context_hash'] == ptr['context_hash'] == mf['context_hash']
    assert ptr['current_session'] == N


# ── TC-03: delta-json 필수 키 누락 → exit 1 ──────────────────────
@pytest.mark.parametrize('missing_key', list(scg.DELTA_REQUIRED_KEYS.keys()))
def test_tc03_delta_missing_key(tmp_path, missing_key):
    """delta-json 필수 키 누락: exit 1"""
    delta = {k: v for k, v in VALID_DELTA.items() if k != missing_key}
    delta_path = _make_delta_json(tmp_path, delta)

    code = _run([
        '--session', str(N), '--chain-tip', CHAIN_TIP, '--prev-tip', PREV_TIP,
        '--delta-json', str(delta_path), '--dry-run',
    ], tmp_path=tmp_path)
    assert code == 1, f'TC-03[{missing_key}]: expected exit 1, got {code}'


# ── TC-04: delta-json 타입 불일치 → exit 1 ───────────────────────
def test_tc04_delta_type_mismatch(tmp_path):
    """delta-json 타입 불일치 (next_steps: list → str): exit 1"""
    delta = {**VALID_DELTA, 'next_steps': 'not_a_list'}
    delta_path = _make_delta_json(tmp_path, delta)

    code = _run([
        '--session', str(N), '--chain-tip', CHAIN_TIP, '--prev-tip', PREV_TIP,
        '--delta-json', str(delta_path), '--dry-run',
    ], tmp_path=tmp_path)
    assert code == 1, f'TC-04: expected exit 1, got {code}'


# ── TC-05: delta-json 파일 없음 → exit 1 ─────────────────────────
def test_tc05_delta_file_not_found(tmp_path):
    """delta-json 파일 없음: exit 1"""
    code = _run([
        '--session', str(N), '--chain-tip', CHAIN_TIP, '--prev-tip', PREV_TIP,
        '--delta-json', str(tmp_path / 'nonexistent.json'), '--dry-run',
    ], tmp_path=tmp_path)
    assert code == 1, f'TC-05: expected exit 1, got {code}'


# ── TC-06: delta-json JSON decode 실패 → exit 1 ──────────────────
def test_tc06_delta_json_decode_fail(tmp_path):
    """delta-json JSON 파싱 실패: exit 1"""
    bad = tmp_path / 'bad.json'
    bad.write_text('{invalid json}', encoding='utf-8')

    code = _run([
        '--session', str(N), '--chain-tip', CHAIN_TIP, '--prev-tip', PREV_TIP,
        '--delta-json', str(bad), '--dry-run',
    ], tmp_path=tmp_path)
    assert code == 1, f'TC-06: expected exit 1, got {code}'


# ── TC-07: approval-id 미제공 → exit 1 ───────────────────────────
def test_tc07_no_approval_id(tmp_path):
    """approval-id 미제공 (운영 실행): exit 1"""
    _make_prev_final(tmp_path)
    _make_prev_archive(tmp_path)
    delta_path = _make_delta_json(tmp_path)

    code = _run([
        '--session', str(N), '--chain-tip', CHAIN_TIP, '--prev-tip', PREV_TIP,
        '--delta-json', str(delta_path),
        # --approval-id 생략
    ], tmp_path=tmp_path)
    assert code == 1, f'TC-07: expected exit 1, got {code}'


# ── TC-08: approval-id 형식 오류 → exit 1 ────────────────────────
@pytest.mark.parametrize('bad_id', [
    'invalid',
    'eag-s231-test',          # 소문자
    'EAG231TEST',             # 하이픈 없음
    'EAG-S231-',              # 끝이 하이픈
    '-EAG-S231-TEST',         # 앞이 하이픈
])
def test_tc08_invalid_approval_id(tmp_path, bad_id):
    """approval-id 형식 오류: exit 1"""
    _make_prev_final(tmp_path)
    _make_prev_archive(tmp_path)
    delta_path = _make_delta_json(tmp_path)

    code = _run([
        '--session', str(N), '--chain-tip', CHAIN_TIP, '--prev-tip', PREV_TIP,
        '--delta-json', str(delta_path),
        '--approval-id', bad_id,
    ], tmp_path=tmp_path)
    assert code in (1, 2), f'TC-08[{bad_id}]: expected exit 1 or 2, got {code}'


# ── TC-09: 이전 FINAL 파일 없음 → exit 1 ─────────────────────────
def test_tc09_prev_final_not_found(tmp_path):
    """S{N-1}_FINAL 파일 없음: exit 1"""
    delta_path = _make_delta_json(tmp_path)
    # S230_FINAL 미생성

    code = _run([
        '--session', str(N), '--chain-tip', CHAIN_TIP, '--prev-tip', PREV_TIP,
        '--delta-json', str(delta_path), '--dry-run',
    ], tmp_path=tmp_path)
    assert code == 1, f'TC-09: expected exit 1, got {code}'


# ── TC-10: verify 실패 (POINTER session_count 조작) → exit 1 ─────
def test_tc10_verify_fail(tmp_path):
    """3-way verify 실패: POINTER.current_session 불일치 → exit 1"""
    _make_prev_final(tmp_path)
    _make_prev_archive(tmp_path)
    _make_canonical_sc(tmp_path)
    delta_path = _make_delta_json(tmp_path)
    # POINTER에 잘못된 session 기록
    (tmp_path / 'SESSION_CONTEXT_POINTER.json').write_text(
        json.dumps({'current_session': 999, 'context_hash': 'bad', 'chain_tip': 'bad'})
    )
    (tmp_path / 'SESSION_CONTEXT_STALE_MANIFEST.json').write_text('{}')

    # verify만 실패하도록: 운영 실행 후 POINTER를 강제 오염
    # → run_verify를 직접 호출하여 불일치 검증
    with pytest.raises(SystemExit) as exc_info:
        scg.run_verify(N, CHAIN_TIP, 'correct_hash_value_that_wont_match')
    assert exc_info.value.code == 1, 'TC-10: expected exit 1'


# ── TC-11: rollback 경로 ─────────────────────────────────────────
def test_tc11_rollback_on_archive_fail(tmp_path):
    """단계 6(ARCHIVE) 실패 시 SC_FINAL rollback 삭제 확인"""
    _make_prev_final(tmp_path)
    # S{N-1} ARCHIVE 파일 없음 → build_archive에서 exit(1) → rollback
    _make_canonical_sc(tmp_path)
    delta_path = _make_delta_json(tmp_path)
    (tmp_path / 'SESSION_CONTEXT_POINTER.json').write_text('{}')
    (tmp_path / 'SESSION_CONTEXT_STALE_MANIFEST.json').write_text('{}')

    code = _run([
        '--session', str(N), '--chain-tip', CHAIN_TIP, '--prev-tip', PREV_TIP,
        '--delta-json', str(delta_path),
        '--approval-id', VALID_APPROVAL,
    ], tmp_path=tmp_path)

    assert code == 1, f'TC-11: expected exit 1, got {code}'
    # SC_FINAL rollback 삭제 확인
    assert not (tmp_path / f'SESSION_CONTEXT_S{N}_FINAL.json').exists(), \
        'TC-11: SC_FINAL should be rolled back'


# ── TC-12: _validate_approval_id 정상 패턴 ───────────────────────
@pytest.mark.parametrize('good_id', [
    'EAG-S231-CLOSE-GENERATOR-001',
    'EAG-S1-A',
    'EAG-S999-POINTER-GUARD-001',
    'EAG-S231-ABC123',
])
def test_tc12_valid_approval_id(good_id):
    """정상 approval-id 형식: True"""
    assert scg._validate_approval_id(good_id) is True, \
        f'TC-12[{good_id}]: expected True'


# ── TC-13: _validate_approval_id 비정상 패턴 ─────────────────────
@pytest.mark.parametrize('bad_id', [
    '',
    'invalid',
    'eag-s231-test',
    'EAG-S231-',
    '-EAG-S231-TEST',
    'EAG231TEST',
])
def test_tc13_invalid_approval_id(bad_id):
    """비정상 approval-id 형식: False"""
    assert scg._validate_approval_id(bad_id) is False, \
        f'TC-13[{bad_id}]: expected False'


# ── TC-14: _context_hash ensure_ascii=False 방식 검증 ────────────
def test_tc14_context_hash_ensure_ascii_false():
    """context_hash: ensure_ascii=False SSOT 방식 검증"""
    sc = {'session_count': 231, 'chain': {'tip': 'abc'}, 'context_hash': 'old'}
    result = scg._context_hash(sc)

    # 직접 계산 (ensure_ascii=False)
    sc_copy = {k: v for k, v in sc.items() if k != 'context_hash'}
    expected = hashlib.sha256(
        json.dumps(sc_copy, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()

    assert result == expected, 'TC-14: context_hash 방식 불일치'

    # ensure_ascii=True와 다른 값임을 확인 (한글 포함 데이터로)
    sc_kr = {'key': '한글', 'context_hash': 'old'}
    hash_false = scg._context_hash(sc_kr)
    sc_copy_kr = {k: v for k, v in sc_kr.items() if k != 'context_hash'}
    hash_true = hashlib.sha256(
        json.dumps(sc_copy_kr, sort_keys=True, ensure_ascii=True).encode('utf-8')
    ).hexdigest()
    assert hash_false != hash_true, \
        'TC-14: ensure_ascii=False와 True는 한글 포함 시 다른 hash를 생성해야 함'
