# Caddy Observation — TKT-S144-001

생성일: 2026-05-23
세션: S144
Ticket: TKT-S144-001
Task: PT-S143-TEST-DEBT-001
단계: caddy_observation → (next) domi_design

---

## 실측 요약

### VPS 현재 상태
- chain.tip: `e685455` (short git hash)
- SESSION_CONTEXT top-level key count: 56
- pytest: 769 pass / 16 fail(기존부채) / 158 skip

### hold_tasks 실측
```
PT-S48-001:             executable=True  ← 정상
PT-S48-002:             executable=True  ← 정상
PT-S48-003:             executable=True  ← 정상
PT-S59-SPLIT-CANDIDATE: executable=True  ← 정상
PT-S59-003:             executable=True  ← 정상
PT-S132-API-001:        executable 필드 없음 ← 문제
```

### sys.modules 오염원
```
test_mcp_http_bridge_v21.py (line 24):
  sys.modules['mcp_audit_broker'] = audit_mock

test_mcp_read_server.py (line 23):
  sys.modules['mcp_audit_broker'] = audit_broker_mock  ← 덮어씀
```

### pytest 알파벳 수집 순서 (문제 재현)
```
test_mcp_http_bridge_v21.py   ← mcp_audit_broker = MagicMock 설정
test_mcp_read_server.py       ← mcp_audit_broker = MagicMock2 덮어씀
test_mcp_server_poc_phase_b.py ← module level import → MOCK 획득
test_mcp_server_poc_phase_c.py ← module level import → MOCK 획득
```

---

## 실패 원인 분석

### Group C (3건) — live-state 불변식 만료
| # | 파일 | 테스트 | 원인 | 수정 방향 |
|---|---|---|---|---|
| C-1 | test_pt_s58_001.py | test_chain_tip_unchanged | 기대값 `3dd5d2fa...` vs 실제 `e685455` | 동적 format 검증으로 전환 |
| C-2 | test_pt_s113_001_operational.py | test_o7_chain_tip_invariant | 동일 | 동일 |
| C-3 | test_pt_s58_001.py | test_hold_tasks_executable_false | PT-S132-API-001 executable 필드 없음 | t.get("executable", False) is False 로 변경 |

### Group B (6건) — sys.modules 오염 → phase_b/c Mock 획득
| # | 파일 | 테스트 | 실패 양상 |
|---|---|---|---|
| B-1 | phase_b | test_b2_authority_separation | AuditBroker=Mock → 파일 미기록 → FAIL |
| B-2 | phase_b | test_b2_t3_timeout_raises | AuditBroker=Mock → 예외 미발생 |
| B-3 | phase_b | test_b3_audit_unverified_result | AuditBroker=Mock → RuntimeError 미발생 |
| B-4 | phase_c | test_tc9_deny_audit_recorded | read_audit_log=Mock → 빈 결과 |
| B-5 | phase_c | test_tc10_allow_audit_10_fields | 동일 |
| B-6 | phase_c | test_tc12_nonce_hash_in_audit | 동일 |

수정 방향: test_mcp_server_poc_phase_b/c.py 최상단에
`sys.modules.pop('mcp_audit_broker', None)` 추가 → 실제 모듈 로드 강제

### Group A (7건) — 기대값 불일치 + 오염 연쇄
| # | 파일 | 테스트 | 원인 | 수정 방향 |
|---|---|---|---|---|
| A-1 | test_mcp_http_bridge_v21.py | test_tcb14_initialize | "2.1.0" vs "2.2.0" | "2.2.0"로 수정 |
| A-2 | test_mcp_hard_containment.py | test_ht6_hct05_audit_failure | 실행 시점 mcp_audit_broker=Mock | 내부 import 전 sys.modules.pop 추가 |
| A-3~7 | 미확정 | 추가 5건 | 추가 분석 필요 | 다음 세션에서 pytest 실행으로 특정 |

---

## 다음 단계 (domi_design)에서 필요한 것

1. Group A 나머지 5건 정확한 테스트명 특정
   (방법: VPS에서 pytest --tb=short 실행 후 실패 목록 수집)

2. 각 수정에 대한 설계 확정
   - sys.modules 오염 수정: 어느 파일에 어떤 코드를 추가/수정
   - chain.tip 검증: 동적 format 검증 방식 구체화
   - executable 필드: test 수정 vs SESSION_CONTEXT 수정 중 선택

3. 수정 후 영향 범위 검토
   - sys.modules.pop 추가 시 다른 테스트 영향 없는지

---

## Domi에게 인수 사항

- 원인 분석: Group B(6건), Group C(3건) 완전 확정
- Group A(7건): A-1, A-2 확정. A-3~7 미확정
- 수정 전략 방향: 확정됨 (위 수정 방향 참조)
- 실제 구현은 캐디가 수행 (EAG 필요)
- 다음 세션 시작 전 pytest 실행 결과가 있어야 A-3~7 특정 가능

생성자: Caddy
서명: observation_TKT-S144-001_20260523

---

## 추가 관찰 — SESSION_CONTEXT 분산화 방향 (세션 후반 확인)

비오님 지시: SESSION_CONTEXT 단일 파일 방식 → 주제별 분산 저장 전환

### 현재 문제
- SESSION_CONTEXT_S144_FINAL.json: 233KB (write_file 한도 3.5배 초과)
- top-level keys: 60개 (ceiling 42 상시 초과)
- 세션별 visibility_metrics 필드 무한 누적 구조

### 승인된 방향
`/opt/arss/engine/arss-protocol/context/` 폴더 신설:
- core/, tasks/, agents/, vps/, metrics/, lessons/, archive/
- 에이전트당 읽기 범위: ~16KB (현재 233KB 대비 93% 감소)
- 세션 종료 시 소형 파일 단위 write_file 직접 저장 가능

### 다음 세션(S145) 도미 설계 의뢰 예정
BRIEFING-DOMI-S145-CONTEXT-REFACTOR-001
