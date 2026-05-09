# CRP Master Plan v1.1 FINAL
# Complexity Remediation Program
# S106 | 2026-05-09 | 캐디 작성 | 도미 Final Design Directives 반영
# S110 | 2026-05-09 | §1/§10 갱신 — enforcement_active=true (비오 EAG-3 승인, S109)

---

## 1. 프로젝트 정의

**공식 명칭**: Complexity Remediation Program (CRP)
**내부 철학 명칭**: AIBA Structural Health Recovery

### CRP 철학 LOCK (IMMUTABLE)

CRP는 "복잡도를 제거하는 프로젝트"가 아니다.

CRP는:
- 구조 건강 운영 체계
- 기술 부채 lifecycle governance
- remediation evidence system
- fail-closed remediation OS

이다.

따라서 다음은 **프로젝트 목적 위반**으로 명시한다:
- 숫자 최적화 (CC 수치만 낮추는 행위)
- cosmetic refactor (실질 구조 개선 없는 표면적 변경)
- metric gaming (거버넌스 회피 목적의 분할/위임)

현재 상태: **enforced 모드** (enforcement_active = true)
enforcement 전환 완료: 전환 조건 9개 전항목 충족 + 비오(Joshua) EAG-3 승인 (S109, 2026-05-09)

---

## 2. Baseline (S105 측정)

| 항목 | 결과 |
|---|---|
| Mean CC | 3.19 (A등급) |
| F등급 함수 | 3건 |
| E등급 함수 | 2건 |
| C등급 이상 위험 라인 | 91 lines |
| 최고 위험 함수 | rpu_issue (CC=49) |
| 측정 도구 | radon cc v6.0.1 |
| 제외 경로 | venv/, 99_LEGACY/ |

---

## 3. 핵심 원칙

### 원칙 1 — 신규 부채 생성 차단 우선
기존 부채 전체 제거보다 새로운 위험 부채 생성 차단을 우선한다.

### 원칙 2 — 레거시 즉시 강제 금지
다음 함수는 운영 안정화 전까지 aggressive decomposition 금지:
- rpu_issue
- run_shadow_pipeline
- classify_stage0

### 원칙 3 — 복잡도는 허용 가능하나 추적 불가능성은 금지
추적 불가능 / owner 없음 / 만료 없음 / registry 미등재 상태가 위험.

### 원칙 4 — 수치 최적화보다 구조 안정성 우선
다음은 거버넌스 회피로 간주:
- 의미 없는 wrapper 함수 증가
- excessive delegation
- split-only refactor
- readability degradation
- file fragmentation

---

## 4. 복잡도 Gate 기준

### 신규 함수
| 기준 | 판정 |
|---|---|
| CC <= 10 | PASS |
| CC 11~15 | REVIEW |
| CC > 15 | HARD STOP |

### 기존 함수
| 기준 | 판정 |
|---|---|
| CC >= 20 | managed (registry 등재) |
| CC >= 30 | HARD STOP candidate |

### 시스템 레벨
| 기준 | 판정 |
|---|---|
| mean CC > 5.0 | SYSTEM REVIEW REQUIRED |

---

## 5. 3단계 치료 Tier

### Tier-1 — Critical Care (CC >= 49)
- 대상: rpu_issue (DEBT-105-001)
- 현재 허용: 분석 / 구조 분해 전략 / dependency mapping / verification planning
- 현재 금지: 실제 refactor 실행
- 제니 검증: Mandatory (5개 항목 전체)
  - regression review
  - shadow complexity review
  - registry lifecycle review
  - governance avoidance review
  - rollback risk review

### Tier-2 — Intensive Care (CC 20~48)
- 함수 수정 시 reduction plan 요구 가능
- reduction ratio 추적
- debt lifecycle 등록 필수
- 제니 검증: Conditional

### Tier-3 — Regular Care (CC 11~19)
- advisory warning
- recommendation mode
- trend monitoring
- 제니 검증: Advisory Monitoring

---

## 6. Anti-Regression Lock

CRP 대상 함수는 CC 감소 여부와 무관하게 regression test PASS 없이 치료 완료 불가.

| 상황 | 판정 |
|---|---|
| CC 감소 + Regression PASS | 치료 후보 |
| CC 감소 + Regression FAIL | 사고 |
| CC 감소 없음 + 구조 안정성 개선 있음 | REVIEW (캐디 단독 불가) |
| CC 감소만 있고 기능 보증 없음 | INVALID |

REVIEW 처리 주체:
- 캐디: implementability + evidence package 작성
- 도미: 구조적 타당성 판단
- 제니: trust/adversarial validation
- 비오: 최종 EAG 판단

---

## 7. Shadow Complexity 대응

### 정의
함수 CC만 낮추고 함수 수 증가 / 파일 파편화 / excessive delegation이 발생하는 현상.

### 추가 측정 지표 (advisory)
| 지표 | 목적 |
|---|---|
| File Total CC | 파일 총 복잡도 |
| Function Count | 함수 폭증 감지 |
| Complexity Density | LOC 대비 복잡도 |
| Delegation Depth | 과도 위임 감지 |
| Wrapper Ratio | 의미 없는 분할 감지 |

현재: advisory only / STOP 아님 / trend analysis 중심

---

## 8. remediation_type

### v1.1 정책: 단일 primary 타입 유지

복합 remediation(예: EXTRACT_HELPER + SIMPLIFY_BRANCH)은 현재 advisory 단계에서 schema complexity 폭증 방지를 위해 단일 타입 유지.
향후 primary_remediation_type + secondary_remediation_types 구조 확장 검토 가능 (별도 EAG 필요).

### 허용 Enum
| 값 | 설명 |
|---|---|
| DECOMPOSE | 함수 분해 |
| EXTRACT_HELPER | 헬퍼 함수 추출 |
| MERGE_DUPLICATE | 중복 통합 |
| INLINE_TRIVIAL | 불필요한 단계 인라인 |
| SIMPLIFY_BRANCH | 분기 단순화 |
| REMOVE_DEAD_PATH | 미사용 경로 제거 |
| NORMALIZE_VALIDATION | 검증 로직 정규화 |
| ISOLATE_SIDE_EFFECT | 사이드이펙트 격리 |
| SPLIT_IO_FROM_LOGIC | IO/로직 분리 |
| TEST_ONLY_GUARD | 테스트 전용 가드 |
| EMERGENCY_PATCH | 긴급 패치 (EAG-EMERGENCY 전용) |
| DOCUMENTED_EXCEPTION | 문서화된 예외 처리 |

원칙: 포괄 표현("REFACTOR" 등) 금지. enum 외 값은 REVIEW 처리.

---

## 9. EAG-EMERGENCY 절차

### 정의
"선행 EAG-1/EAG-2 압축 + 사후 보강 검증" 구조.
"규칙 우회"가 아니라 "선조치 후증적·후검증".

### HARD LOCK: expiration_session 필수
expiration_session 없는 EAG-EMERGENCY = **INVALID**.
Emergency Override는 반드시 "정상 거버넌스로 복귀 예정 상태"여야 한다. 영구 emergency 상태 금지.

### 허용 완화
| 항목 | 일반 EAG | EAG-EMERGENCY |
|---|---|---|
| 설계 패키지 전체 분량 | 필수 | 생략 가능 |
| EAG-2 PEC 전체 형식 | 필수 | 축약 가능 |
| 비오 승인 | 필수 | **생략 불가** |
| 증적 기록 | 필수 | **생략 불가** |
| 사후 검증 | 필수 | **생략 불가 (사후 수행)** |
| registry 기록 | 필수 | **생략 불가** |
| expiration_session | 필수 | **생략 불가 (HARD LOCK)** |

### Emergency Flow (8단계)
| 단계 | 내용 | 필수 여부 |
|---|---|---|
| 1 | 비오 emergency 승인 | 필수 |
| 2 | emergency_reason / affected_function / expected_risk / followup_obligation / expiration_session 기록 | 필수 |
| 3 | 최소 안전성 검토 | 필수 |
| 4 | 긴급 수정 허용 | — |
| 5 | 사후 CRP_HISTORY_LOG 기록 | 필수 |
| 6 | exceptional_debt_registry EMERGENCY_OVERRIDE 상태로 등록 또는 갱신 | 필수 |
| 7 | expiration_session 내 제니 사후 검증 | 필수 |
| 8 | followup remediation 여부 결정 | 필수 |

---

## 10. Advisory → Enforced 전환 트리거

### 전환 원칙
9개 조건 전항목 충족 + 비오 EAG 승인. 단 1개 미충족 시 advisory 유지.

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

### Enforced 전환 후 Advisory Rollback 조건

Enforced는 irreversible 선언 금지. 다음 조건 발생 시 advisory rollback 검토:

| 트리거 | 설명 |
|---|---|
| false-positive HARD STOP 급증 | Gate 오탐으로 정상 개발 차단 |
| governance deadlock 발생 | CRP Gate로 인한 EAG chain 순환 차단 |
| remediation bottleneck 폭증 | 처리 대기 debt 과다로 시스템 정체 |
| emergency override 남용 | EAG-EMERGENCY 비정상 빈도 증가 |
| pair validation instability 증가 | CRP enforcement 영향으로 핵심 파이프라인 불안정 |

rollback 실행: 비오 판단 후 EAG 승인 필요.

### 전환 전 허용/금지 테이블
| 행위 | advisory | enforced |
|---|---|---|
| 복잡도 측정 | ✅ | ✅ |
| 경고 발행 | ✅ | ✅ |
| registry 등록 | ✅ | ✅ |
| 계획 수립 | ✅ | ✅ |
| 핵심 함수 강제 리팩토링 | ❌ | EAG 후 허용 |
| enforcement gate 활성화 | ❌ | ✅ |
| rpu_issue 직접 분해 | ❌ | EAG 후 허용 |
| HARD STOP gate 실제 차단 | ❌ (경고만) | ✅ |

---

## 11. 실행 단계 로드맵

| Phase | 명칭 | 착수 조건 | 내용 |
|---|---|---|---|
| A | Governance Foundation | — | baseline / registry / gate control / advisory governance **(상당 수준 완료)** |
| B | Remediation Planning | **advisory 단계에서 착수 가능** | dependency mapping / decomposition strategy / risk analysis (실행 아님) |
| C | Controlled Surgical Refactor | Advisory → Enforced 전환 조건 충족 후 EAG 승인 | Tier-1 decomposition / selective remediation |
| D | Continuous Health Governance | Phase C 이후 | continuous monitoring / trend analysis / health scoring |

**Planning(Phase B)과 Execution(Phase C)은 분리한다.**
Phase B는 advisory 상태에서도 가능. Phase C만 enforced 조건 필요.

---

## 12. 현재 금지 항목

- 핵심 엔진 aggressive refactor
- rpu_issue decomposition 실행
- shadow pipeline 구조 이동
- pair validation 구조 변경
- runtime ordering rewrite
- enforcement 활성화 (EAG 없이)
- 임의 debt 제거
