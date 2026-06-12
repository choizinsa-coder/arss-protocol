"""
pointer_guard_s231.py
SESSION BOOT 시 POINTER staleness 자동 감지 스크립트

EAG: EAG-S231-POINTER-GUARD-001
위치: tools/guard/pointer_guard_s231.py
설계 근거: PT-S231-POINTER-GUARD-001 (도미 2차 설계 + Beo 최종 보완)

SESSION BOOT 호출 경로:
  python3 /opt/arss/engine/arss-protocol/tools/guard/pointer_guard_s231.py
  exit 0 → BOOT 계속 진행
  exit 1 → HARD STOP, Beo 보고 후 대기
"""
import json
import sys
from pathlib import Path

ROOT = Path('/opt/arss/engine/arss-protocol')
errors = []


# ── 1. 최신 SESSION_CONTEXT_S*_FINAL.json glob (basename 기준 파싱)
try:
    final_files = list(ROOT.glob('SESSION_CONTEXT_S*_FINAL.json'))
    if not final_files:
        print('[FAIL] SESSION_CONTEXT_S*_FINAL.json 파일이 존재하지 않습니다.')
        sys.exit(1)
    latest_file = max(
        final_files,
        key=lambda p: int(p.name.split('_S')[1].split('_')[0])
    )
except Exception as e:
    print(f'[FAIL] FINAL 파일 탐색 실패: {e}')
    sys.exit(1)


# ── 2. 최신 FINAL 파일 로드 → expected 값 산출
try:
    with open(latest_file, encoding='utf-8') as f:
        sc = json.load(f)
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


# ── 3. POINTER 파일 로드
try:
    pointer_path = ROOT / 'SESSION_CONTEXT_POINTER.json'
    with open(pointer_path, encoding='utf-8') as f:
        ptr = json.load(f)
except FileNotFoundError as e:
    print(f'[FAIL] POINTER 파일 없음: {e}')
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f'[FAIL] POINTER 파일 JSON decode 실패: {e}')
    sys.exit(1)


# ── 4. 6-check (pointer_verify_s230.py checks = [...] 패턴 계승)
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


# ── 5. 결과 출력 및 exit code
print()
if errors:
    print(f'POINTER GUARD FAILED — {len(errors)} error(s)')
    for e in errors:
        print(f'  >> {e}')
    sys.exit(1)
else:
    print('POINTER GUARD PASSED: ALL 6 CHECKS OK')
    sys.exit(0)
