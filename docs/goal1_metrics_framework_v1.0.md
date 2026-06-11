# Goal 1 Metrics Framework v1.0

**EAG:** EAG-S224-METRICS-GOV-001
**DEP:** DEP-S224-GOV-001
**설계:** 도미 (CSO)
**검증:** 제니 TRUST_READY PASS (T-1~T-8 전항목)
**승인:** 비오 (EAG-S224-METRICS-GOV-001, S224)
**배포:** S224
**대상 태스크:** PT-S115-OBS-001 연장 과제

---

## 목적

Goal 1 (오케스트레이션 완성) 달성 여부를 객관적으로 측정하기 위한
M1~M5 지표 공식 정의, 측정 주기, 판정 기준, session_journal 연계 규칙,
및 Goal 1 종료 판정 절차를 확정한다.

신규 기능 개발보다 거버넌스 체계 완결성을 우선한다.
DEP 건수 확보 자체를 목표로 하지 않는다.

---

## 1. M1~M5 공식 정의

### M1 — DEP Chain Completion Rate

**목적:** Goal 1의 핵심 KPI. 세션 내 DEP 체인이 설계부터 EAG 승인까지 완주되는 비율을 측정한다.

**정의:**
```
해당 세션에서 시작된 DEP 체인 중 EAG 승인까지 완료된 비율
```

**계산식:**
```
M1 = 완료 DEP 수 / 시작 DEP 수
```

**"DEP 시작" 판정 기준:**
비오님이 `DEP-Sxxx-xxx` 형식으로 명시적으로 선언한 시점.
(묵시적 설계 의뢰, 브리핑 발행만으로는 "시작"으로 집계하지 않는다.)

**측정 주기:** 세션 단위

---

### M2 — Domi Governance Compliance

**목적:** 도미의 역할 경계(설계/전략 전담, 동적 VPS 관측 금지) 준수 확인.

**정의:**
```
도미 호출 세션에서 RAW 근거 기반 설계를 수행했는가
```

**PASS 조건:**
- read_file 직접 조회 기반 설계
- 추론 전용 설계 아님
- 역할 경계(ROLE_DRIFT) 위반 없음

**FAIL 조건:**
- DOMI_INFERENCE_UNVERIFIABLE 인시던트 발생
- ROLE_DRIFT 인시던트 발생
- RAW 미관측 상태에서 수치 인용 설계

**측정 주기:** 세션 단위

---

### M3 — Jeni First-Pass Validation Rate

**목적:** 설계 품질 측정. 제니가 1차 검증에서 바로 TRUST_READY를 통과하는 비율(First-Pass Yield).

**정의:**
```
제니 1차 검증에서 TRUST_READY PASS한 비율
```

**계산식:**
```
M3 = 1차 PASS 건수 / 전체 제니 검증 건수
```

**중요 — First-Pass Yield 원칙:**
```
TRUST_NOT_READY → 수정 → PASS = 최종 PASS이나 M3는 FAIL로 집계
```
이 지표는 "최종 성공 여부"가 아니라 "1차 통과율"을 측정한다.

**측정 주기:** 세션 단위

---

### M4 — Incident-Free Session Rate

**목적:** 운영 안정성 측정.

**정의:**
```
INCIDENT 0건 세션의 비율
```

**계산식:**
```
M4 = INCIDENT 없는 세션 수 / 전체 세션 수
```

**N/A:** 없음. 모든 세션에서 계산 가능.

**측정 주기:** 10세션 슬라이딩 윈도우

---

### M5 — Stabilization Compliance

**목적:** Goal 1 운영 절차(M01~M07 체크리스트) 전항목 준수 확인.

**정의:**
```
세션의 caddy_governance_record.stabilization_metrics 내
M01~M07 항목이 전부 PASS인가
```

**PASS:** M01~M07 ALL PASS
**FAIL:** 1개 이상 FAIL 또는 ROLE_VIOLATION 인시던트 발생

**측정 주기:** 세션 단위

---

## 2. N/A 처리 규칙

| 지표 | N/A 적용 조건 | 집계 처리 |
|------|-------------|---------|
| M1 | 해당 세션에 DEP 시작 없음 | 분모 제외 |
| M2 | 도미 미호출 세션 | 분모 제외 |
| M3 | 제니 미호출 세션 | 분모 제외 |
| M4 | N/A 없음 | 항상 집계 |
| M5 | stabilization_metrics 블록 미존재 | 분모 제외 |

**예시 (S222):** 도미/제니 모두 미호출 → M1, M2, M3 모두 N/A.
M4, M5는 정상 집계.

---

## 3. 측정 주기

| 지표 | 주기 | 비고 |
|------|------|------|
| M1 | 세션 단위 | N/A 세션 분모 제외 |
| M2 | 세션 단위 | 도미 미호출 시 N/A |
| M3 | 세션 단위 | 제니 미호출 시 N/A |
| M4 | 10세션 슬라이딩 윈도우 | 전 세션 포함 |
| M5 | 세션 단위 | stabilization_metrics 존재 세션만 |

운영 대시보드: 최근 10세션 rolling average 유지.

---

## 4. PASS/FAIL 판정 기준

| 지표 | PASS 기준 | 근거 |
|------|----------|------|
| M1 | ≥ 80% | 다중 세션 DEP 허용 |
| M2 | 100% | 역할 경계 타협 불허 |
| M3 | ≥ 80% | TRUST_NOT_READY→PASS 사례 현실 반영 |
| M4 | ≥ 90% (10세션) | 운영 안정성 기준 |
| M5 | 100% | 절차 준수 타협 불허 |

**overall 판정 규칙:**
```
M2 FAIL 또는 M5 FAIL → Overall FAIL
그 외 → Overall PASS
```

---

## 5. session_journal 연계 규칙

| event_type | 반영 지표 | 예시 |
|-----------|---------|------|
| `EAG` | M1 | EAG 승인 = DEP 완료 판정 근거 |
| `INCIDENT` | M2, M4 | DOMI_INFERENCE → M2 FAIL, M4 FAIL |
| `OI` | M5, Role Drift, Visibility Metrics | VISIBILITY_METRICS_S{n} |
| `DECISION` | 직접 집계 없음 | 참고 정보 |

**집계 시 SC_FINAL 우선 원칙:**
journal은 WORM으로 세션 중간 상태를 기록하며 수정 불가.
통계 집계의 최종 판정은 `SESSION_CONTEXT_S{n}_FINAL.json` 기준.
(journal 물리 기록 변경이 아닌 해석 규칙이므로 WORM 불변 원칙과 충돌 없음.)

---

## 6. Goal 1 종료 판정 절차

### 종료 조건 (A~E 전부 충족 필요)

| 조건 | 내용 |
|------|------|
| A | 최근 10 DEP 중 M1 ≥ 80% |
| B | 최근 10세션 M5 = 100% |
| C | 최근 10세션 M2 ≥ 90% |
| D | 최근 10세션 M4 ≥ 90% |
| E | OPEN Critical Task = 0건 |

**"10 DEP" 기준:** 본 EAG(EAG-S224-METRICS-GOV-001) 승인으로 확정.
변경 시 별도 EAG 필요.

### 종료 선언 형식

```
EAG-Sxxx-GOAL1-CLOSE
```

비오님 승인 필수. 캐디의 단독 선언 금지.

---

## 7. 소급 적용 (Backfill) 규칙

S221, S222, S223에 소급 적용 가능.
필요 데이터(visibility_metrics_s{n}, caddy_governance_record_s{n}) 존재 확인됨.

**S221 특례:**
- journal: `M07_role_boundary = "IN_PROGRESS"` (세션 진행 중 기록)
- SC_FINAL: `M-07_stabilization_compliance = "PASS"` (세션 종료 후 확정)

→ SC_FINAL 우선 원칙에 따라 S221 M5 = PASS로 최종 집계.

---

## 8. Goal 1 Dashboard 최소 스펙

```json
{
  "session_id": "S{n}",
  "M1": "PASS | FAIL | N/A",
  "M2": "PASS | FAIL | N/A",
  "M3": "PASS | FAIL | N/A",
  "M4": "PASS | FAIL",
  "M5": "PASS | FAIL | N/A",
  "overall": "PASS | FAIL",
  "goal1_dep_progress": "{완료 DEP누적}/{목표}"
}
```

---

## 9. Trust Advisory (제니, S224)

자동화 구현(Goal 2 착수 이후) 단계에서 아래 사항을 검토할 것.

> M3를 First-Pass Yield FAIL로 엄격 집계할 경우, 에이전트가 1차 TRUST_NOT_READY를 피하기 위해 Shadow Channel(사전 타협)을 시도하는 인센티브가 생길 수 있다. 자동화 구현 시 패널티 차등 가중치 도입을 권고한다.

현재 문서 전용 산출물에는 영향 없음. 적용 여부는 비오님 판단 사항.

---

*생성: S224 / 최종 수정: S224*
