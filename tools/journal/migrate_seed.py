"""
migrate_seed.py
session_journal S210~S216 seed 데이터 초기 로드
EAG-S217-PHASE1-001
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from session_journal_writer import migrate_seed_data

# S210~S216 key_decisions (visibility_metrics_s{n}.key_decisions 기반)
SEED_ENTRIES = [
    # S210
    {"session_id": "S210", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "EAG-S210-TOKEN-001: validate_beo_token() 4단계 완전 인증 구현"}},
    {"session_id": "S210", "actor": "beo", "event_type": "EAG",
     "details": {"decision": "EAG-S210-EXEC-001: Gate 0 + MUTATING_COMMANDS — 실행 파이프라인 동결"}},
    {"session_id": "S210", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "EAG-3 count 2/3 달성 (S211→3/3 예정)"}},
    # S211
    {"session_id": "S211", "actor": "beo", "event_type": "EAG",
     "details": {"decision": "EAG-3 ENFORCE 모드 전환 완료 (consecutive_clean_sessions=3)"}},
    {"session_id": "S211", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "validate_beo_token BEO_RELEASE_ prefix 패턴 (Jeni 거버넌스 위반 방어)"}},
    {"session_id": "S211", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "Jeni v4.4.0 NO_PARTS Exponential Backoff 3회"}},
    {"session_id": "S211", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "AES v1.0 증거 표준 제정"}},
    # S213
    {"session_id": "S213", "actor": "beo", "event_type": "EAG",
     "details": {"decision": "EAG-S213-AES-PHASE2-001: eag_artifact_collector.py 배포"}},
    {"session_id": "S213", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "mcp_read_server.py ARSS_HUB_ROOT 제니 독립 관측 경로 추가"}},
    {"session_id": "S213", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "OAuth secrets 관리 정책 v1.0 제정"}},
    # S214
    {"session_id": "S214", "actor": "beo", "event_type": "EAG",
     "details": {"decision": "EAG-S214-OBS-001: mcp_read_server.py v1.1.0 EVIDENCE_CODE_ROOT 추가"}},
    {"session_id": "S214", "actor": "beo", "event_type": "EAG",
     "details": {"decision": "EAG-S214-JENI-MODEL-001: gemini-2.5-flash→gemini-2.0-flash"}},
    # S215
    {"session_id": "S215", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "INC-S214-001 해소 — MCP 인프라 정상, ask_domi VPS 파일 읽기 확인"}},
    {"session_id": "S215", "actor": "beo", "event_type": "INCIDENT",
     "details": {"decision": "INC-S215-002 해소 — jeni service 파일 gemini-2.0-flash 수정"}},
    {"session_id": "S215", "actor": "beo", "event_type": "DECISION",
     "details": {"decision": "AIBA Council 비전 정의 — Shared Memory + Shared Deliberation"}},
    # S216
    {"session_id": "S216", "actor": "beo", "event_type": "EAG",
     "details": {"decision": "gemini-2.0-flash→2.5-flash-lite 교체 완료 (EAG-S216-JENI-MODEL-001)"}},
    {"session_id": "S216", "actor": "beo", "event_type": "EAG",
     "details": {"decision": "Phase 0 정체성 주입 표준 COMPLETE (EAG-S216-PHASE0-001)"}},
    {"session_id": "S216", "actor": "beo", "event_type": "EAG",
     "details": {"decision": "AES Phase2 TRUST_READY 확정 — 3세션 이월 종료 (EAG-S213-AES-PHASE2-001)"}},
    {"session_id": "S216", "actor": "caddy", "event_type": "DECISION",
     "details": {"decision": "INC-S208-001 Hash Mismatch 0건 확인 (8세션 연속)"}},
    {"session_id": "S216", "actor": "jeni", "event_type": "INCIDENT",
     "details": {"decision": "VALIDATION_INCONSISTENCY-S216-001 관측·기록"}},
]

if __name__ == "__main__":
    print("=== session_journal seed migration ===")
    result = migrate_seed_data(SEED_ENTRIES)
    if result["ok"]:
        print(f"[OK] migrated_count={result['migrated_count']}")
        print(f"     last_entry_hash={result['last_entry_hash']}")
    else:
        print(f"[FAIL] {result['error']}")
        sys.exit(1)
