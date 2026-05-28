"""
regenerate_runtime_s124.py
목적: SESSION_STATE_RUNTIME.json을 S124 기준으로 재생성
EAG: 비오(Joshua) S124 승인
실행: python3 regenerate_runtime_s124.py
"""
import json
import shutil
from pathlib import Path
from datetime import datetime

ARSS_ROOT = Path('/opt/arss/engine/arss-protocol')
RUNTIME_PATH = ARSS_ROOT / 'SESSION_STATE_RUNTIME.json'
BACKUP_PATH = ARSS_ROOT / 'SESSION_STATE_RUNTIME.json.bak_s124'

# S124 기준값 (SESSION_CONTEXT_S124_FINAL 기반)
SESSION_COUNT = 124
GENERATED_AT = '2026-05-13T00:00:00.000+09:00'
CHAIN_TIP = '3dd5d2fa5c98c8d6ddf0bfaff33479c4a1b7c6d1b800d7fa4d07208b4d65de30'
CHAIN_PHASE = 'PHASE 1 COMPLETE'
CHAIN_LAST_RPU = 'RPU-0043'

def main():
    # 1. 기존 파일 백업
    if RUNTIME_PATH.exists():
        shutil.copy2(RUNTIME_PATH, BACKUP_PATH)
        print(f'[BACKUP] {BACKUP_PATH}')
    else:
        print('[WARN] 기존 RUNTIME 파일 없음 — 백업 생략')

    # 2. 신규 RUNTIME 구조 생성
    # _zone, _source_session, _generated_from 필드 유지 (runtime_generator.py 검증 필수 필드)
    runtime_new = {
        "activation_allowed": False,
        "session_count": SESSION_COUNT,
        "generated_at": GENERATED_AT,
        "chain": {
            "phase": CHAIN_PHASE,
            "phase1_completed": "2026-03-19",
            "last_rpu": CHAIN_LAST_RPU,
            "tip": CHAIN_TIP,
            "note": "S124 PT-S115-BOOT-001 전환 완료. SESSION_BOOT.json vnext-1.0 교체. RUNTIME 재생성."
        },
        "agent_focus": {
            "caddy": "S124: PT-S115-BOOT-001 전환 완료. SESSION_BOOT.json 교체(vnext-1.0). session_open_rules BOOT+RUNTIME 방식 등재. session_close_rules 정식 전환. SESSION_STATE_RUNTIME.json S124 기준 재생성.",
            "domi": "S124: 대기 중. 다음 설계 의뢰 없음.",
            "jeni": "S124: 대기 중. 다음 검증 의뢰 없음."
        },
        "session_reentry": {
            "context_summary": {
                "value": "S124: PT-S115-BOOT-001 전환 완료. SESSION_BOOT.json vnext-1.0 교체. BOOT+RUNTIME 분리 업로드 방식 S125~부터 적용."
            },
            "next_session_recommended_tasks": [
                "1. [MEDIUM] PT-S115-OBS-001: Visibility Metrics 정규 운용 계속",
                "2. [ADVISORY] 제니 TA-4: _ref_class 마커 누락 방지 확인",
                "3. [INFO] S125부터 업로드 방식 변경 적용 — SESSION_BOOT.json + SESSION_STATE_RUNTIME.json 분리 업로드"
            ],
            "eag_required_next": False,
            "pending_eag_items": [],
            "_purpose": "세션 종료 시 캐디 작성 의무. 다음 세션 첫 로드 시 에이전트 즉시 업무 진입 보장.",
            "generated_by": "caddy",
            "generated_at": GENERATED_AT
        },
        "sync_meta": {
            "version": "v1.0",
            "sync_architecture": "B2 — Phase 2-B 전환 완료",
            "last_session_date": "2026-05-13",
            "session_status": "OPEN",
            "upload_mode": "BOOT+RUNTIME (S124~ 정식 전환)",
            "evolution_score": {
                "status": "DISABLED",
                "disabled_reason": "evolution_score SOFT_KILL DIS-049",
                "disabled_date": "2026-04-20"
            }
        },
        "_zone": "SESSION_STATE_RUNTIME",
        "_source_session": SESSION_COUNT,
        "_generated_from": "SESSION_CONTEXT_S124_FINAL.json"
    }

    # 3. 파일 저장
    with open(RUNTIME_PATH, 'w', encoding='utf-8') as f:
        json.dump(runtime_new, f, ensure_ascii=False, indent=2)
    print(f'[WRITE] {RUNTIME_PATH}')

    # 4. 검증
    with open(RUNTIME_PATH, 'r', encoding='utf-8') as f:
        verify = json.load(f)

    assert verify['session_count'] == SESSION_COUNT, 'session_count 불일치'
    assert verify['chain']['tip'] == CHAIN_TIP, 'chain.tip 불일치'
    assert verify['_zone'] == 'SESSION_STATE_RUNTIME', '_zone 불일치'
    assert verify['_source_session'] == SESSION_COUNT, '_source_session 불일치'
    assert 'activation_allowed' in verify, 'activation_allowed 누락'

    print('[VERIFY] session_count:', verify['session_count'])
    print('[VERIFY] chain.tip:', verify['chain']['tip'][:16], '...')
    print('[VERIFY] _zone:', verify['_zone'])
    print('[VERIFY] _source_session:', verify['_source_session'])
    print('[VERIFY] ALL PASS')

if __name__ == '__main__':
    main()
