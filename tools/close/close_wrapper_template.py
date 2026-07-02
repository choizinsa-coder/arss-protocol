# close_wrapper_template.py
# EAG-S312-CLOSE-WRAPPER-001
# SESSION CLOSE 시 캐디가 write_script로 세션별 wrapper를 생성할 때 사용하는 정식 템플릿
# 위치: tools/close/close_wrapper_template.py (참조 전용, 직접 실행 안 함)
#
# 사용법:
#   1. SESSION CLOSE 시 캐디가 이 템플릿을 기반으로
#      close_wrapper_s{n}.py를 write_script로 생성
#   2. 생성 시 SESSION_N / CHAIN_TIP / PREV_TIP / APPROVAL_ID / DELTA 를
#      실데이터로 대체하여 본문에 직접 삽입
#   3. run_script로 실행 → read_file로 session_close_result.json 확인
#
# 제니 TRUST-ADVISORY 반영 항목:
#   - /tmp delta 파일은 finally 블록에서 반드시 삭제 (sanitization 강제)
#   - wrapper 스크립트도 SESSION CLOSE 완료 후 삭제 권장

import subprocess
import json
import os
import sys
from datetime import datetime, timezone

ROOT = '/opt/arss/engine/arss-protocol'
GENERATOR = f'{ROOT}/tools/close/session_close_generator.py'
SANDBOX = f'{ROOT}/tools/sandbox/caddy/active'
RESULT_PATH = f'{SANDBOX}/session_close_result.json'

# ================================================================
# 아래 4개 변수는 SESSION CLOSE 시 실데이터로 대체
# ================================================================
SESSION_N  = 0                 # 예: 312
CHAIN_TIP  = 'PLACEHOLDER'    # 예: 'df828e1'
PREV_TIP   = 'PLACEHOLDER'    # 예: '920cc55'
APPROVAL_ID = 'PLACEHOLDER'   # 예: 'EAG-S312-CLOSE-001'

# DELTA: 9개 필수 키 (session_close_generator.py DELTA_REQUIRED_KEYS 기준)
DELTA = {
    'session_reentry': {
        'resume_point': '',       # 세션 요약
        'eag_carryover': '',      # S{n+1} EAG 이월
    },
    'next_steps': [],             # list[str]
    'agent_focus': {
        'caddy': '', 'domi': '', 'jeni': '', 'beo': ''
    },
    'pytest_status': {
        'total_passed': 0, 'total_failed': 0, 'total_skipped': 0,
        'last_run_session': 0, 'note': ''
    },
    'system_changes': {
        'deployed_session': 0,
        'commits': [],            # list[str]
        'changes': [],            # list[str]
        'eag_chain': '',
        'pytest_result': ''
    },
    'caddy_governance_record': {
        'session': 0, 'date': '',
        'eag_gates_this_session': [],
        'incidents': [],
        'oi_observations': [],
        'caddy_self_report': [],
        'notable': '',
        'stabilization_metrics': {}
    },
    'visibility_metrics': {
        'session': 0, 'date': '',
        'M-04_session_delta_size': '',
        'M-05_archive_file_status': '',
        'M-06_active_task_load': 0,
        'M-07_stabilization_compliance': '',
        'chain_tip': '',
        'pytest_result': '',
        'key_decisions': []
    },
    'session_delta': {
        'from_session': 0, 'to_session': 0,
        'summary': '', 'incident_count': 0, 'eag_count': 0
    },
    'sync_meta': {
        'last_close_session': 0,
        'close_method': 'session_close_generator.py',
        'verified': True
    },
}
# ================================================================

DELTA_TMP = f'/tmp/delta_s{SESSION_N}.json'


def main():
    generated_at = datetime.now(timezone.utc).isoformat()
    result = {
        'success': False,
        'exit_code': -1,
        'session': SESSION_N,
        'approval_id': APPROVAL_ID,
        'stdout': '',
        'stderr': '',
        'generated_at': generated_at,
    }

    try:
        # Step 1: delta JSON → /tmp/
        with open(DELTA_TMP, 'w', encoding='utf-8') as f:
            json.dump(DELTA, f, ensure_ascii=False, indent=2)

        # Step 2: session_close_generator.py subprocess 호출
        proc = subprocess.run(
            [
                sys.executable, GENERATOR,
                '--session',     str(SESSION_N),
                '--chain-tip',   CHAIN_TIP,
                '--prev-tip',    PREV_TIP,
                '--delta-json',  DELTA_TMP,
                '--approval-id', APPROVAL_ID,
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

        result['exit_code'] = proc.returncode
        result['stdout']    = proc.stdout
        result['stderr']    = proc.stderr
        result['success']   = (proc.returncode == 0)
        if proc.returncode != 0:
            result['error_stage'] = 'generator'

    except Exception as e:
        result['stderr']      = str(e)
        result['error_stage'] = 'wrapper'

    finally:
        # Step 3: /tmp delta 즉시 삭제 (제니 TRUST-ADVISORY 시니타이제이션)
        try:
            if os.path.exists(DELTA_TMP):
                os.remove(DELTA_TMP)
        except Exception:
            pass

    # Step 4: 결과 JSON 저장 (캐디 read_file 확인용)
    with open(RESULT_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 성공: exit 0, 실패: exit 1 (제네레이터 exit code 동일하게 전파)
    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
