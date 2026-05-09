# CRP Governance Supplements v1.1 FINAL
# EAG-EMERGENCY Rule / Automatic Discharge Lifecycle / Advisory→Enforced Transition
# S106 | 2026-05-09 | 캐디 작성 | 도미 Final Design Directives 반영
# S110 | 2026-05-09 | §3 전환 조건 테이블 갱신 — enforcement_active=true (비오 EAG-3 승인, S109)

---

## 문서 1 — EAG-EMERGENCY Rule

### 정의

EAG-EMERGENCY는 기존 EAG를 전부 생략하지 않는다.
"선행 EAG-1/EAG-2 압축 + 사후 보강 검증" 구조.
"규칙 우회"가 아니라 "선조치 후증적·후검증".

---

### HARD LOCK: expiration_session 필수

**expiration_session 없는 EAG-EMERGENCY = INVALID.**

Emergency Override는 반드시 "정상 거버넌스로 복귀 예정 상태"여야 한다.
영구 emergency 상태 금지.

---

### 허용 완화 항목

| 항목 | 일반 EAG | EAG-EMERGENCY |
|---|---|---|
| 설계 패키지 전체 분량 | 필수 | 생략 가능 |
| EAG-2 PEC 전체 형식 | 필수 | 축약 가능 |
| 비오 승인 | 필수 | **생략 불가** |
| 증적 기록 | 필수 | **생략 불가** |
| 사후 검증 | 필수 | **생략 불가 (사후 수행)** |
| registry 기록 | 필수 | **생략 불가** |
| expiration_session | 선택 | **생략 불가 (HARD LOCK)** |

---

### Emergency Flow (8단계)

| 단계 | 내용 | 필수 |
|---|---|---|
| 1 | 비오 emergency 승인 | 필수 |
| 2 | 기록: emergency_reason / affected_function / expected_risk / followup_obligation / expiration_session | 필수 |
| 3 | 최소 안전성 검토 | 필수 |
| 4 | 긴급 수정 허용 | — |
| 5 | 사후 CRP_HISTORY_LOG 기록 (is_emergency=true) | 필수 |
| 6 | exceptional_debt_registry EMERGENCY_OVERRIDE 상태 등록 또는 갱신 | 필수 |
| 7 | expiration_session 내 제니 사후 검증 | 필수 |
| 8 | followup remediation 여부 결정 | 필수 |

---

## 문서 2 — Automatic Discharge Lifecycle

### 정의

exceptional_debt_registry에 등록된 active_debt가 퇴원 조건을 모두 충족하면 `DISCHARGED` 상태로 전환.
물리 삭제 금지. active_debt → discharged_debt 상태 전환 후 이력 영구 보존.

---

### 퇴원 조건 (5개 전항목 충족 필수)

| # | 조건 | 판정 기준 |
|---|---|---|
| 1 | after_cc <= 10 | CRP_HISTORY_LOG 기록 기준 |
| 2 | regression test PASS | regression_test_result = PASS |
| 3 | shadow complexity 미탐지 | shadow_complexity_check = CLEAN |
| 4 | 제니 검증 PASS 또는 advisory accepted | jeni_verification_result = PASS 또는 WAIVED |
| 5 | CRP_HISTORY_LOG 기록 완료 | discharge_history_ref 존재 |

---

### Discharge 상태 흐름

```
ACTIVE
  ↓ (치료 착수)
IN_PROGRESS
  ↓ (치료 완료 후 검증 대기)
REVIEW
  ↓ (퇴원 조건 5개 전항목 충족)
DISCHARGED ──────────────────────────────────┐
  ↓ (동일 함수 CC 재악화 감지)              │
ACTIVE (기존 debt_id 재활성화)   ←──────────┘
  (신규 debt_id 발급 금지 / history_refs 유지)

※ 예외 경로:
ACTIVE → ESCALATED (3세션 이상 미개선)
ACTIVE → EMERGENCY_OVERRIDE (EAG-EMERGENCY 발동)
EMERGENCY_OVERRIDE → IN_PROGRESS (사후 검증 후)
IN_PROGRESS → ESCALATED (검증 실패 반복)
ESCALATED → HARD STOP candidate (비오 판단)
```

---

### Reactivation 정책 (DISCHARGED → ACTIVE)

| 항목 | 규칙 |
|---|---|
| debt_id | 기존 debt_id 재활성화. 신규 발급 금지. |
| status | DISCHARGED → ACTIVE 또는 ESCALATED |
| history_refs | 기존 배열 보존 후 신규 record append |
| reactivation_count | +1 증가 |
| CRP_HISTORY_LOG | is_reactivation=true record 생성 필수 |
| 목적 | 치료→재발→재치료 lifecycle 추적 유지 |

---

### ESCALATION 트리거

| 조건 | 결과 |
|---|---|
| REVIEW 상태 3세션 이상 미개선 | ESCALATED 전환 가능 |
| ESCALATED 후 1세션 내 미처리 | HARD STOP candidate |
| regression_test_result = FAIL 반복 | forced remediation review |
| shadow_complexity_check = DETECTED 반복 | architectural audit 가능 |

---

### discharged_debt 보존 정책

- 물리 삭제 금지
- registry discharged_debt 섹션에 summary 영구 유지
- 상세 이력은 CRP_HISTORY_LOG에 영구 보존
- 장기 비대화 시 별도 archive projection 설계 가능 (별도 EAG 필요)

---

## 문서 3 — Advisory → Enforced 전환 트리거 테이블

### 전환 원칙

9개 조건 전항목 충족 + 비오 EAG 승인.
단 1개 미충족 시 advisory 유지.
**Enforced는 irreversible 선언 금지 — rollback 조건 존재.**

---

### 전환 조건 테이블

| # | 조건 | 상태 |
|---|---|---|
| 1 | PT-S81-ARCH-001 Phase 3 완료 | ✅ 완료 (S107) |
| 2 | boot/runtime pair validation 안정화 | ✅ 완료 (S90) |
| 3 | shadow pipeline 안정화 | ✅ 완료 (S98) |
| 4 | delta integrity 안정화 | ✅ 완료 (S103) |
| 5 | fail-closed ordering 검증 완료 | ✅ 완료 (S103) |
| 6 | exceptional_debt_registry v1.0 확정 | ✅ 완료 (S105) |
| 7 | CRP_HISTORY_LOG 구조 확정 | ✅ 완료 (S106) |
| 8 | 제니 TRUST_READY | ✅ 완료 (S109) |
| 9 | 비오 EAG 승인 | ✅ 완료 (S109) |

**전환 완료**: enforcement_active = true | 승인자: 비오(Joshua) EAG-3 | 승인 세션: S109 | 승인 일시: 2026-05-09

---

### Advisory Rollback 조건 (Enforced → Advisory)

| 트리거 | 설명 |
|---|---|
| false-positive HARD STOP 급증 | Gate 오탐으로 정상 개발 차단 |
| governance deadlock 발생 | CRP Gate로 EAG chain 순환 차단 |
| remediation bottleneck 폭증 | 처리 대기 debt 과다로 시스템 정체 |
| emergency override 남용 | EAG-EMERGENCY 비정상 빈도 증가 |
| pair validation instability 증가 | CRP enforcement 영향으로 핵심 파이프라인 불안정 |

rollback 실행: 비오 판단 + EAG 승인 필요.

---

### Phase B / C 분리 원칙

| Phase | 명칭 | 착수 조건 |
|---|---|---|
| B | Remediation Planning | **advisory 상태에서 착수 가능** |
| C | Controlled Surgical Refactor | Advisory → Enforced 전환 조건 충족 후 EAG 승인 |

Planning(Phase B)과 Execution(Phase C)은 분리한다.

---

### 전환 전/후 허용·금지 테이블

| 행위 | advisory | enforced |
|---|---|---|
| 복잡도 측정 | ✅ | ✅ |
| 경고 발행 | ✅ | ✅ |
| registry 등록 | ✅ | ✅ |
| 계획 수립 (Phase B) | ✅ | ✅ |
| 핵심 함수 강제 리팩토링 | ❌ | EAG 후 허용 |
| enforcement gate 활성화 | ❌ | ✅ |
| rpu_issue 직접 분해 | ❌ | EAG 후 허용 |
| HARD STOP gate 실제 차단 | ❌ (경고만) | ✅ |
