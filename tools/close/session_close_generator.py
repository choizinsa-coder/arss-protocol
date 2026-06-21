"""
session_close_generator.py
SESSION CLOSE 5-file 번들 생성 정식 도구

EAG: EAG-S231-CLOSE-GENERATOR-001
위치: tools/close/session_close_generator.py
설계 근거: PT-S231-SESSION-CLOSE-GENERATOR (도미 설계 + Beo 보완 + 제니 TRUST_READY)
S273 개정: EAG-S273-BOOTCLOSE-REDESIGN-001
  - Step 5.5 Freeze Sync: journal last_entry_hash 자동 갱신
  - Step 5.6 Freeze Verification: govdoc_freeze_gate.py 즉시 검증
  - close_manifest.json 생성 (run_script 의존 제거)
  - CLOSE SUCCESS 조건: Freeze Verification PASS

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
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path('/opt/arss/engine/arss-protocol')
KST = timezone(timedelta(hours=9))

APPROVAL_ID_PATTERN = re.compile(r'^EAG-S\d+-[A-Z0-9][A-Z0-9-]*[A-Z0-9]?$')

# ── DEP-S249-TIERD-MIGRATE-001 (목표 ③) ──────────────────────────
N_RETENTION = 10
_RECORD_KEY_RE = re.compile(r'^(caddy_governance_record_s|visibility_metrics_s)(\d+)$')

GROUP_D_MIGRATE_WHITELIST = frozenset({
    'goal2_declaration', 'goal2_governance_rule',
    'visibility_metrics_current', 'on_the_horizon',
})

CANONICAL_EXCLUDE_KEYS = frozenset({
    'session_count', 'chain', 'session_delta', 'updated_at', 'generated_at',
    'context_hash', 'schema_version', 'sync_meta', 'pytest_status',
})
CEILING_LIMIT = 42

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

# ── S273: Freeze Sync 대상 경로 ───────────────────────────────────
FREEZE_TEST_PATH = ROOT / 'tests/test_goal1_freeze.py'
JOURNAL_PATH = ROOT / 'session_journal/session_journal.jsonl'
FREEZE_GATE_SCRIPT = ROOT / 'tools/guard/govdoc_freeze_gate.py'
FREEZE_SYNC_REPORT_PATH = ROOT / 'tools/close/freeze_sync_report.json'
CLOSE_MANIFEST_PATH = ROOT / 'tools/close/close_manifest.json'


# ── 유틸 ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(KST).isoformat()


def _today() -> str:
    return datetime.now(KST).strftime('%Y-%m-%d')


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _context_hash(sc: dict) -> str:
    sc_copy = {k: v for k, v in sc.items() if k != 'context_hash'}
    return hashlib.sha256(
        json.dumps(sc_copy, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()


def _validate_approval_id(approval_id: str) -> bool:
    return bool(APPROVAL_ID_PATTERN.match(approval_id))


def _rollback(generated_files: list) -> None:
    for fp in generated_files:
        try:
            Path(fp).unlink(missing_ok=True)
            print(f'[ROLLBACK] 삭제: {Path(fp).name}')
        except Exception as e:
            print(f'[ROLLBACK-WARN] 삭제 실패: {Path(fp).name} — {e}')


# ── S273 신규: Step 5.5 Freeze Sync ──────────────────────────────

def step_5_5_freeze_sync() -> str:
    """
    session_journal.jsonl 마지막 entry의 entry_hash를 추출하여
    tests/test_goal1_freeze.py FROZEN_JOURNAL_LAST_ENTRY_HASH를 갱신.
    freeze_sync_report.json 생성.
    반환: 새 hash 문자열
    """
    # 1. journal 마지막 entry 읽기
    if not JOURNAL_PATH.exists():
        print('[FAIL] step_5.5: session_journal.jsonl 없음')
        sys.exit(1)

    last_entry = None
    with open(JOURNAL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                last_entry = json.loads(line)

    if last_entry is None:
        print('[FAIL] step_5.5: session_journal.jsonl 비어 있음')
        sys.exit(1)

    new_hash = last_entry.get('entry_hash', '')
    if not new_hash:
        print('[FAIL] step_5.5: entry_hash 필드 없음')
        sys.exit(1)

    # 2. test_goal1_freeze.py 현재 hash 읽기
    freeze_test_content = FREEZE_TEST_PATH.read_text(encoding='utf-8')

    # FROZEN_JOURNAL_LAST_ENTRY_HASH 현재 값 추출
    import re as _re
    pattern = _re.compile(
        r'(FROZEN_JOURNAL_LAST_ENTRY_HASH\s*=\s*\(\s*")[0-9a-f]+"(\s*\))',
        _re.MULTILINE
    )
    match = pattern.search(freeze_test_content)
    if not match:
        print('[FAIL] step_5.5: FROZEN_JOURNAL_LAST_ENTRY_HASH 패턴 미발견')
        sys.exit(1)

    old_hash = match.group(0).split('"')[1]

    if old_hash == new_hash:
        print(f'[OK] step_5.5: hash 동일 — 갱신 불필요 ({new_hash[:16]}...)')
        report = {
            'status': 'SKIPPED',
            'reason': 'hash identical',
            'old_hash': old_hash,
            'new_hash': new_hash,
            'updated_at': _now(),
        }
        with open(FREEZE_SYNC_REPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return new_hash

    # 3. sed -i 방식으로 교체
    result = subprocess.run(
        ['sed', '-i',
         f's/{old_hash}/{new_hash}/',
         str(FREEZE_TEST_PATH)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f'[FAIL] step_5.5: sed 실행 실패 — {result.stderr}')
        sys.exit(1)

    print(f'[OK] step_5.5: FROZEN_JOURNAL_LAST_ENTRY_HASH 갱신')
    print(f'     old: {old_hash}')
    print(f'     new: {new_hash}')

    # 4. freeze_sync_report.json 생성
    report = {
        'status': 'UPDATED',
        'old_hash': old_hash,
        'new_hash': new_hash,
        'updated_at': _now(),
    }
    with open(FREEZE_SYNC_REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'[OK] step_5.5: freeze_sync_report.json 생성')

    return new_hash


# ── S273 신규: Step 5.6 Freeze Verification ──────────────────────

def step_5_6_freeze_verification():
    """
    govdoc_freeze_gate.py 즉시 실행.
    PASS: 계속 / FAIL: REPORT & WAIT (sys.exit(1))
    """
    result = subprocess.run(
        [sys.executable, str(FREEZE_GATE_SCRIPT)],
        capture_output=True, text=True,
        cwd=str(ROOT)
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print('[FAIL] step_5.6: Freeze Verification FAIL — CLOSE 중단 (FAIL_CLOSED)')
        print('[FAIL] REPORT & WAIT: 비오님께 즉시 보고하십시오.')
        sys.exit(1)
    print('[OK] step_5.6: Freeze Verification PASS — CLOSE SUCCESS 조건 충족')


# ── S273 신규: close_manifest.json 생성 (run_script 대체) ─────────

def build_close_manifest(n: int, chain_tip: str, computed_hash: str) -> dict:
    """
    5개 파일의 존재·크기·SHA256을 기록한 manifest 생성.
    Caddy가 MCP read_file로 검증 가능 — run_script 의존 제거.
    """
    files_to_verify = [
        ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json',
        ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json',
        ROOT / 'SESSION_CONTEXT.json',
        ROOT / 'SESSION_CONTEXT_POINTER.json',
        ROOT / 'SESSION_CONTEXT_STALE_MANIFEST.json',
    ]

    manifest_entries = []
    all_ok = True
    for fp in files_to_verify:
        if not fp.exists() or fp.stat().st_size == 0:
            all_ok = False
            manifest_entries.append({
                'file': fp.name,
                'exists': fp.exists(),
                'size_bytes': fp.stat().st_size if fp.exists() else 0,
                'sha256': None,
                'status': 'MISSING_OR_EMPTY',
            })
        else:
            manifest_entries.append({
                'file': fp.name,
                'exists': True,
                'size_bytes': fp.stat().st_size,
                'sha256': _sha256_file(fp),
                'status': 'OK',
            })

    manifest = {
        'schema': 'close_manifest_v1',
        'session': n,
        'chain_tip': chain_tip,
        'context_hash': computed_hash,
        'generated_at': _now(),
        'all_files_ok': all_ok,
        'files': manifest_entries,
        'verification_method': 'MCP read_file OBSERVE',
    }

    with open(CLOSE_MANIFEST_PATH, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    status = 'OK' if all_ok else 'FAIL'
    print(f'[{status}] close_manifest.json 생성 ({len(manifest_entries)}개 파일 기록)')
    return manifest


# ── 기존 함수들 (원본 유지) ───────────────────────────────────────

def identify_archive_candidates(sc: dict, n: int, N: int = N_RETENTION) -> dict:
    threshold = n - N + 1
    candidates = {}
    for k, v in sc.items():
        m = _RECORD_KEY_RE.match(k)
        if m and int(m.group(2)) < threshold:
            candidates[k] = v
        elif k in GROUP_D_MIGRATE_WHITELIST:
            candidates[k] = v
    return candidates


def verify_archive_integrity(archive_path: Path, candidates: dict) -> bool:
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


def load_delta(delta_json_path: str) -> dict:
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


def apply_delta(sc: dict, n: int, chain_tip: str, prev_tip: str, delta: dict):
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
    sc.pop(f'system_changes_s{n - 4}', None)
    archive_candidates = identify_archive_candidates(sc, n)
    return sc, archive_candidates


def build_archive(n: int, archive_candidates: dict) -> dict:
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
        'data': archive_candidates,
    }


def run_verify(n: int, expected_chain: str, expected_hash: str) -> None:
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
            errors.append(f'chain.tip mismatch')
        else:
            print(f'[OK] chain.tip == {expected_chain}')
        if sc.get('context_hash') != expected_hash:
            errors.append('SC_FINAL.context_hash mismatch')
        else:
            print(f'[OK] SC_FINAL.context_hash == {expected_hash[:16]}...')
        with open(ROOT / 'SESSION_CONTEXT_POINTER.json', encoding='utf-8') as f:
            ptr = json.load(f)
        if ptr.get('current_session') != n:
            errors.append(f'POINTER.current_session mismatch')
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
        description='SESSION CLOSE 5-file 번들 생성 도구 (S273 개정)'
    )
    parser.add_argument('--session',     type=int, required=True)
    parser.add_argument('--chain-tip',   required=True)
    parser.add_argument('--prev-tip',    required=True)
    parser.add_argument('--delta-json',  required=True)
    parser.add_argument('--dry-run',     action='store_true')
    parser.add_argument('--approval-id', default='')
    parser.add_argument('--ceiling-override', action='store_true')
    args = parser.parse_args()

    os.umask(0o027)

    n         = args.session
    chain_tip = args.chain_tip
    prev_tip  = args.prev_tip

    delta = load_delta(args.delta_json)
    sc = load_prev_final(n)
    sc, archive_candidates = apply_delta(sc, n, chain_tip, prev_tip, delta)

    if args.dry_run:
        sc_sim = dict(sc)
        for k in archive_candidates:
            sc_sim.pop(k, None)
        sim_hash = _context_hash(sc_sim)
        print(f'[DRY-RUN] 산출 예정: SESSION_CONTEXT_S{n}_FINAL.json')
        print(f'[DRY-RUN]   session_count  = {n}')
        print(f'[DRY-RUN]   chain_tip      = {chain_tip}')
        print(f'[DRY-RUN]   context_hash   = {sim_hash}')
        print(f'[DRY-RUN] [③] Tier D 이관 대상 = {len(archive_candidates)}개')
        print(f'[DRY-RUN] S273 추가: Step 5.5 Freeze Sync + Step 5.6 Freeze Verification')
        print(f'[DRY-RUN] S273 추가: close_manifest.json (run_script 대체)')
        sys.exit(0)

    if not args.approval_id or not _validate_approval_id(args.approval_id):
        print('[FAIL] --approval-id 미제공 또는 형식 불일치')
        sys.exit(1)

    generated_files: list = []

    # ── [③ 원자 순서] archive 기록 + 무결성 검증
    archive_path = ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json'
    try:
        archive = build_archive(n, archive_candidates)
        with open(archive_path, 'w', encoding='utf-8') as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json')
    except SystemExit:
        raise
    except Exception as e:
        print(f'[FAIL] ARCHIVE 기록 실패: {e}')
        sys.exit(1)

    if not verify_archive_integrity(archive_path, archive_candidates):
        archive_path.unlink(missing_ok=True)
        print('[FAIL] archive 무결성 검증 실패 — FAIL_CLOSED')
        sys.exit(1)

    for k in archive_candidates:
        sc.pop(k, None)
    migrated = len(archive_candidates)
    print(f'[OK] active pop 확정 — migrated {migrated} keys')

    canon = len([k for k in sc.keys() if k not in CANONICAL_EXCLUDE_KEYS])
    if canon > CEILING_LIMIT and not args.ceiling_override:
        print(f'[FAIL] canonical key {canon} > 천장 {CEILING_LIMIT} — HARD_STOP')
        sys.exit(1)
    elif canon >= 41:
        print(f'[SYSTEM_REVIEW] canonical key {canon} — 천장 임박')
    else:
        print(f'[OK] canonical key {canon} <= 천장 {CEILING_LIMIT}')

    sc['context_hash'] = _context_hash(sc)
    computed_hash = sc['context_hash']

    # Step 5: SC_FINAL 저장
    sc_final_path = ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json'
    try:
        with open(sc_final_path, 'w', encoding='utf-8') as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        generated_files.append(sc_final_path)
        print(f'[OK] SESSION_CONTEXT_S{n}_FINAL.json')
    except Exception as e:
        print(f'[FAIL] SC_FINAL 저장 실패: {e}')
        sys.exit(1)

    # Step 7: canonical overwrite
    sc_canonical_path = ROOT / 'SESSION_CONTEXT.json'
    try:
        with open(sc_canonical_path, 'w', encoding='utf-8') as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT.json canonical overwrite')
    except Exception as e:
        _rollback(generated_files)
        print(f'[FAIL] SESSION_CONTEXT.json overwrite 실패: {e}')
        sys.exit(1)

    # Step 8: POINTER 갱신
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
        print(f'[OK] SESSION_CONTEXT_POINTER.json')
    except Exception as e:
        _rollback(generated_files)
        print(f'[FAIL] POINTER 갱신 실패: {e}')
        sys.exit(1)

    # Step 9: STALE_MANIFEST 갱신
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
        print(f'[OK] SESSION_CONTEXT_STALE_MANIFEST.json')
    except Exception as e:
        _rollback(generated_files)
        print(f'[FAIL] STALE_MANIFEST 갱신 실패: {e}')
        sys.exit(1)

    # ── S273 Step 5.5: Freeze Sync
    print()
    print('── S273 Step 5.5 Freeze Sync ──────────────────────────────')
    step_5_5_freeze_sync()

    # ── S273 Step 5.6: Freeze Verification (CLOSE SUCCESS 조건)
    print()
    print('── S273 Step 5.6 Freeze Verification ──────────────────────')
    step_5_6_freeze_verification()

    # ── S273: close_manifest.json 생성 (run_script 대체)
    print()
    print('── S273 close_manifest.json 생성 ──────────────────────────')
    build_close_manifest(n, chain_tip, computed_hash)

    # Step 10: 3-way consistency 검증 (기존 유지)
    print()
    print('── 3-way consistency verify ──────────────────────')
    run_verify(n, chain_tip, computed_hash)

    print()
    print('[CLOSE SUCCESS] Freeze Verification PASS — SESSION CLOSE 완료 조건 충족')
    sys.exit(0)


if __name__ == '__main__':
    main()
