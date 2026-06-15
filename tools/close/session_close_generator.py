"""
session_close_generator.py
SESSION CLOSE 5-file 번들 생성 정식 도구

EAG: EAG-S231-CLOSE-GENERATOR-001
위치: tools/close/session_close_generator.py
설계 근거: PT-S231-SESSION-CLOSE-GENERATOR (도미 설계 + Beo 보완 + 제니 TRUST_READY)

사용법:
  # dry-run (파일 write 없음 — 산출 예정 경로·payload 출력만)
  python3 session_close_generator.py \\
      --session 231 --chain-tip abc1234 --prev-tip 0e4383e \\
      --delta-json /path/to/delta.json --dry-run

  # 실제 실행 (EAG approval-id 필수)
  python3 session_close_generator.py \\
      --session 231 --chain-tip abc1234 --prev-tip 0e4383e \\
      --delta-json /path/to/delta.json \\
      --approval-id EAG-S231-CLOSE-GENERATOR-001
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path('/opt/arss/engine/arss-protocol')
KST = timezone(timedelta(hours=9))

APPROVAL_ID_PATTERN = re.compile(r'^EAG-S\d+-[A-Z0-9][A-Z0-9-]*[A-Z0-9]?$')

# ── DEP-S249-TIERD-MIGRATE-001 (목표 ③) ──────────────────────────
# 정착조건(a): 이관 대상 = caddy_governance_record_s* / visibility_metrics_s*
#              AND 세션번호 < (n - N_RETENTION + 1)
# 범위 격리: goal2_*, 구조 키, system_changes(GOV-003)는 비대상.
N_RETENTION = 10
_RECORD_KEY_RE = re.compile(r'^(caddy_governance_record_s|visibility_metrics_s)(\d+)$')

# delta-json 필수 키 9개 스펙 (비오님 확정)
DELTA_REQUIRED_KEYS = {
    'session_reentry':         dict,
    'next_steps':              list,
    'agent_focus':             dict,
    'pytest_status':           dict,
    'system_changes':          dict,
    'caddy_governance_record': dict,
    'visibility_metrics':      dict,
    'session_delta':           dict,
    'sync_meta':               dict,
}


# ── 유틸 ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(KST).isoformat()


def _today() -> str:
    return datetime.now(KST).strftime('%Y-%m-%d')


def _context_hash(sc: dict) -> str:
    """context_hash 계산 — ensure_ascii=False SSOT (S229/S230 FINAL 계열 근거)"""
    sc_copy = {k: v for k, v in sc.items() if k != 'context_hash'}
    return hashlib.sha256(
        json.dumps(sc_copy, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()


def _validate_approval_id(approval_id: str) -> bool:
    """형식 검증만 수행 (비오님 확정 — 실제 레지스트리 조회 없음)"""
    return bool(APPROVAL_ID_PATTERN.match(approval_id))


def _rollback(generated_files: list) -> None:
    """이번 실행 신규 생성 파일만 삭제.
    주의: Tier D archive 파일은 이관 데이터를 보유하므로 이 목록에 넣지 않는다(손실 방지)."""
    for fp in generated_files:
        try:
            Path(fp).unlink(missing_ok=True)
            print(f'[ROLLBACK] 삭제: {Path(fp).name}')
        except Exception as e:
            print(f'[ROLLBACK-WARN] 삭제 실패: {Path(fp).name} — {e}')


def identify_archive_candidates(sc: dict, n: int, N: int = N_RETENTION) -> dict:
    """[③ 1단계] 비파괴 식별: aged record 키를 {key: value}로 반환. sc 미변경.
    정착조건(a): 패턴(caddy_governance_record_s*/visibility_metrics_s*) AND 세션 < (n-N+1)."""
    threshold = n - N + 1
    candidates = {}
    for k, v in sc.items():
        m = _RECORD_KEY_RE.match(k)
        if m and int(m.group(2)) < threshold:
            candidates[k] = v
    return candidates


def verify_archive_integrity(archive_path: Path, candidates: dict) -> bool:
    """[③ 2단계] 무결성 검증: 기록된 archive 파일을 다시 읽어
    data에 모든 candidate 키가 보존됐는지 확인. 정착조건(b) 역조회 소스 = data."""
    try:
        with open(archive_path, encoding='utf-8') as f:
            written = json.load(f)
    except Exception as e:
        print(f'[INTEGRITY-FAIL] archive 재읽기 오류: {e}')
        return False
    data = written.get('data', {})
    for k, v in candidates.items():
        if k not in data or data[k] != v:
            print(f'[INTEGRITY-FAIL] 키 누락/불일치: {k}')
            return False
    return True


# ── 단계별 처리 함수 ─────────────────────────────────────────────

def load_delta(delta_json_path: str) -> dict:
    """단계 1: delta-json 로드 + 9키 검증"""
    try:
        with open(delta_json_path, encoding='utf-8') as f:
            delta = json.load(f)
    except FileNotFoundError:
        print(f'[FAIL] delta-json 파일 없음: {delta_json_path}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'[FAIL] delta-json JSON decode 실패: {e}')
        sys.exit(1)

    for key, expected_type in DELTA_REQUIRED_KEYS.items():
        if key not in delta:
            print(f'[FAIL] delta-json 필수 키 누락: {key}')
            sys.exit(1)
        if not isinstance(delta[key], expected_type):
            print(f'[FAIL] delta-json 타입 불일치: {key} '
                  f'(expected {expected_type.__name__}, '
                  f'got {type(delta[key]).__name__})')
            sys.exit(1)
    return delta


def load_prev_final(n: int) -> dict:
    """단계 2: S{N-1}_FINAL 로드"""
    prev_path = ROOT / f'SESSION_CONTEXT_S{n - 1}_FINAL.json'
    try:
        with open(prev_path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f'[FAIL] S{n - 1}_FINAL 파일 없음: {prev_path}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'[FAIL] S{n - 1}_FINAL JSON decode 실패: {e}')
        sys.exit(1)


def apply_delta(sc: dict, n: int, chain_tip: str, prev_tip: str,
                delta: dict):
    """단계 3~4: delta 적용 + [③] aged record 키 비파괴 식별.
    반환: (sc, archive_candidates). context_hash는 main()에서 조건부 pop 이후 산출."""
    now = _now()

    sc['session_count'] = n
    sc['chain'] = {'session': n, 'prev_tip': prev_tip, 'tip': chain_tip}
    sc['updated_at'] = now
    sc['generated_at'] = now

    sc['session_reentry']                   = delta['session_reentry']
    sc['next_steps']                        = delta['next_steps']
    sc['agent_focus']                       = delta['agent_focus']
    sc['pytest_status']                     = delta['pytest_status']
    sc[f'system_changes_s{n}']              = delta['system_changes']
    sc[f'caddy_governance_record_s{n}']     = delta['caddy_governance_record']
    sc[f'visibility_metrics_s{n}']          = delta['visibility_metrics']
    sc['session_delta']                     = delta['session_delta']
    sc['sync_meta']                         = delta['sync_meta']

    # GOV-003: system_changes_s{N-4} 키 제거 (ceiling 42 유지) — ③ 범위 외, 기존 유지
    sc.pop(f'system_changes_s{n - 4}', None)

    # [③ 1단계] aged record 키 비파괴 식별 (제거는 main()에서 archive 성공 후)
    archive_candidates = identify_archive_candidates(sc, n)

    # context_hash는 여기서 산출하지 않음 — 조건부 pop 이후 최종 sc 기준 main()에서 1회 산출
    return sc, archive_candidates


def build_archive(n: int, archive_candidates: dict) -> dict:
    """단계 6용: ARCHIVE 구조 생성 + [③] aged record 키 무손실 기록.
    migrated_keys_count / total_tier_d_keys 실효화."""
    prev_archive_path = ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n - 1}.json'
    try:
        with open(prev_archive_path, encoding='utf-8') as f:
            prev_arch = json.load(f)
        total_tier_d = prev_arch.get('_archive_meta', {}).get('total_tier_d_keys', 78)
    except FileNotFoundError:
        print(f'[FAIL] S{n - 1} ARCHIVE 파일 없음: {prev_archive_path}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'[FAIL] S{n - 1} ARCHIVE JSON decode 실패: {e}')
        sys.exit(1)

    migrated = len(archive_candidates)
    return {
        '_archive_meta': {
            'archive_session':    n,
            'archive_date':       _today(),
            'base_archive':       f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n - 1}.json',
            'tier_d_change':      f'+{migrated} keys migrated' if migrated else '변동 없음',
            'migrated_keys_count': migrated,
            'total_tier_d_keys':  total_tier_d + migrated,
        },
        'data': archive_candidates,   # [③] 정착조건(b) 역조회 소스
    }


def run_verify(n: int, expected_chain: str, expected_hash: str) -> None:
    """단계 10: 3-way consistency 검증 (verify_s230_close.py 패턴 계승)"""
    errors = []

    files = [
        ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json',
        ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json',
        ROOT / 'SESSION_CONTEXT.json',
        ROOT / 'SESSION_CONTEXT_POINTER.json',
        ROOT / 'SESSION_CONTEXT_STALE_MANIFEST.json',
    ]
    for fp in files:
        if not fp.exists():
            errors.append(f'MISSING: {fp.name}')
        elif fp.stat().st_size == 0:
            errors.append(f'EMPTY: {fp.name}')
        else:
            print(f'[OK] {fp.name} ({fp.stat().st_size} bytes)')

    try:
        with open(ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json', encoding='utf-8') as f:
            sc = json.load(f)
        if sc.get('session_count') != n:
            errors.append(f'session_count: {sc.get("session_count")} != {n}')
        else:
            print(f'[OK] session_count == {n}')

        if sc.get('chain', {}).get('tip') != expected_chain:
            errors.append(f'chain.tip: {sc.get("chain", {}).get("tip")} != {expected_chain}')
        else:
            print(f'[OK] chain.tip == {expected_chain}')

        if sc.get('context_hash') != expected_hash:
            errors.append('SC_FINAL.context_hash mismatch')
        else:
            print(f'[OK] SC_FINAL.context_hash == {expected_hash[:16]}...')

        with open(ROOT / 'SESSION_CONTEXT_POINTER.json', encoding='utf-8') as f:
            ptr = json.load(f)
        if ptr.get('current_session') != n:
            errors.append(f'POINTER.current_session: {ptr.get("current_session")} != {n}')
        else:
            print(f'[OK] POINTER.current_session == {n}')
        if ptr.get('chain_tip') != expected_chain:
            errors.append(f'POINTER.chain_tip mismatch')
        else:
            print(f'[OK] POINTER.chain_tip == {expected_chain}')
        if ptr.get('context_hash') != expected_hash:
            errors.append('POINTER.context_hash mismatch')
        else:
            print(f'[OK] POINTER.context_hash 일치')

        with open(ROOT / 'SESSION_CONTEXT_STALE_MANIFEST.json', encoding='utf-8') as f:
            mf = json.load(f)
        if mf.get('context_hash') != expected_hash:
            errors.append('MANIFEST.context_hash mismatch')
        else:
            print(f'[OK] MANIFEST.context_hash 일치')

    except Exception as e:
        errors.append(f'VERIFY 읽기 오류: {e}')

    print()
    if errors:
        print(f'VERIFICATION FAILED — {len(errors)} error(s)')
        for e in errors:
            print(f'  >> {e}')
        sys.exit(1)
    else:
        print('VERIFICATION PASSED: ALL CHECKS OK')


# ── main ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='SESSION CLOSE 5-file 번들 생성 도구'
    )
    parser.add_argument('--session',     type=int, required=True,
                        help='생성할 세션 번호 (예: 231)')
    parser.add_argument('--chain-tip',   required=True,
                        help='해당 세션 git commit hash')
    parser.add_argument('--prev-tip',    required=True,
                        help='직전 세션 git commit hash')
    parser.add_argument('--delta-json',  required=True,
                        help='delta 정보 JSON 파일 경로')
    parser.add_argument('--dry-run',     action='store_true',
                        help='파일 write 없이 산출 예정 경로·payload 출력만')
    parser.add_argument('--approval-id', default='',
                        help='EAG approval ID (운영 실행 시 필수)')
    args = parser.parse_args()

    os.umask(0o027)  # S243: arss 640 보안 정책

    n          = args.session
    chain_tip  = args.chain_tip
    prev_tip   = args.prev_tip

    # ── 단계 1: delta-json 로드 + 9키 검증
    delta = load_delta(args.delta_json)

    # ── 단계 2: S{N-1}_FINAL 로드
    sc = load_prev_final(n)

    # ── 단계 3~4: delta 적용 + [③] aged 키 비파괴 식별
    sc, archive_candidates = apply_delta(sc, n, chain_tip, prev_tip, delta)

    # ── dry-run: 파일 write 전면 금지 — 경로·payload 출력 후 종료
    if args.dry_run:
        # 이관 성공을 가정한 최종 sc로 시뮬레이션 hash 산출
        sc_sim = dict(sc)
        for k in archive_candidates:
            sc_sim.pop(k, None)
        sim_hash = _context_hash(sc_sim)
        print(f'[DRY-RUN] 산출 예정: SESSION_CONTEXT_S{n}_FINAL.json')
        print(f'[DRY-RUN]   session_count  = {n}')
        print(f'[DRY-RUN]   chain_tip      = {chain_tip}')
        print(f'[DRY-RUN]   context_hash   = {sim_hash} (이관 반영 시뮬레이션)')
        print(f'[DRY-RUN] [③] Tier D 이관 대상 aged record 키 = {len(archive_candidates)}개 '
              f'(보존 윈도우 N={N_RETENTION})')
        print(f'[DRY-RUN] 산출 예정: SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json '
              f'(data: {len(archive_candidates)} keys)')
        print(f'[DRY-RUN] 산출 예정: SESSION_CONTEXT.json (canonical overwrite)')
        print(f'[DRY-RUN] 산출 예정: SESSION_CONTEXT_POINTER.json')
        print(f'[DRY-RUN]   current_session = {n}')
        print(f'[DRY-RUN] 산출 예정: SESSION_CONTEXT_STALE_MANIFEST.json')
        print(f'[DRY-RUN] 원자 순서: archive 기록+검증 성공 시에만 active pop')
        print(f'[DRY-RUN] 3-way verify: SKIP (파일 미생성 — 운영 실행 시 수행)')
        sys.exit(0)

    # ── 운영 실행: approval-id 형식 검증 (write 진입 전 gate)
    if not args.approval_id or not _validate_approval_id(args.approval_id):
        print('[FAIL] --approval-id 미제공 또는 형식 불일치 '
              '(예: EAG-S231-CLOSE-GENERATOR-001)')
        sys.exit(1)

    generated_files: list = []   # 주의: archive 파일은 손실 방지 위해 미포함

    # ── [③ 원자 순서] 단계 6: archive 기록 + 무결성 검증을 active pop보다 선행
    archive_path = ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json'
    try:
        archive = build_archive(n, archive_candidates)
        with open(archive_path, 'w', encoding='utf-8') as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json '
              f'({archive_path.stat().st_size} bytes, data {len(archive_candidates)} keys)')
    except SystemExit:
        raise
    except Exception as e:
        print(f'[FAIL] ARCHIVE 기록 실패: {e}')
        sys.exit(1)

    # 무결성 검증 — 실패 시 FAIL_CLOSED (pop 미수행, 손실 0)
    if not verify_archive_integrity(archive_path, archive_candidates):
        archive_path.unlink(missing_ok=True)   # 불량 archive 제거 (키는 active sc에 잔존)
        print('[FAIL] archive 무결성 검증 실패 — pop 미수행, 데이터 손실 0. 중단(FAIL_CLOSED).')
        sys.exit(1)

    # ── [③] archive 기록+검증 성공 → 이때만 active pop 확정 (정착조건 c)
    for k in archive_candidates:
        sc.pop(k, None)
    migrated = len(archive_candidates)
    print(f'[OK] [③] active pop 확정 — migrated {migrated} keys (보존 윈도우 N={N_RETENTION})')

    # ── [③] 최종 sc(이관 반영) 기준 context_hash 1회 산출
    sc['context_hash'] = _context_hash(sc)
    computed_hash = sc['context_hash']

    # ── 단계 5: SESSION_CONTEXT_S{N}_FINAL.json 저장 (이관 반영 sc)
    sc_final_path = ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json'
    try:
        with open(sc_final_path, 'w', encoding='utf-8') as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        generated_files.append(sc_final_path)
        print(f'[OK] SESSION_CONTEXT_S{n}_FINAL.json '
              f'({sc_final_path.stat().st_size} bytes)')
    except Exception as e:
        print(f'[FAIL] SC_FINAL 저장 실패: {e}')
        sys.exit(1)

    # ── 단계 7: SESSION_CONTEXT.json canonical overwrite
    sc_canonical_path = ROOT / 'SESSION_CONTEXT.json'
    try:
        with open(sc_canonical_path, 'w', encoding='utf-8') as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT.json canonical overwrite '
              f'({sc_canonical_path.stat().st_size} bytes)')
    except Exception as e:
        _rollback(generated_files)
        print(f'[FAIL] SESSION_CONTEXT.json overwrite 실패: {e}')
        sys.exit(1)

    # ── 단계 8: SESSION_CONTEXT_POINTER.json 갱신
    pointer_path = ROOT / 'SESSION_CONTEXT_POINTER.json'
    try:
        pointer = {
            'current_session': sc['session_count'],
            'canonical_file':  'SESSION_CONTEXT.json',
            'final_file':      f'SESSION_CONTEXT_S{n}_FINAL.json',
            'chain_tip':       sc['chain']['tip'],
            'prev_tip':        sc['chain']['prev_tip'],
            'context_hash':    sc['context_hash'],
            'generated_at':    _now(),
            'schema_version':  '4.0',
        }
        with open(pointer_path, 'w', encoding='utf-8') as f:
            json.dump(pointer, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT_POINTER.json '
              f'({pointer_path.stat().st_size} bytes)')
    except Exception as e:
        _rollback(generated_files)
        print(f'[FAIL] POINTER 갱신 실패: {e}')
        sys.exit(1)

    # ── 단계 9: SESSION_CONTEXT_STALE_MANIFEST.json 갱신
    manifest_path = ROOT / 'SESSION_CONTEXT_STALE_MANIFEST.json'
    try:
        manifest = {
            'session_count': sc['session_count'],
            'context_hash':  sc['context_hash'],
            'updated_at':    _now(),
            'status':        'FRESH',
        }
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT_STALE_MANIFEST.json '
              f'({manifest_path.stat().st_size} bytes)')
    except Exception as e:
        _rollback(generated_files)
        print(f'[FAIL] STALE_MANIFEST 갱신 실패: {e}')
        sys.exit(1)

    # ── 단계 10: 3-way consistency 검증
    print()
    print('── 3-way consistency verify ──────────────────────')
    run_verify(n, chain_tip, computed_hash)
    sys.exit(0)


if __name__ == '__main__':
    main()
