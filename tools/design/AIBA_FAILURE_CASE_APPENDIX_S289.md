# AIBA Runtime Failure Case 부록 (S289)

**문서 ID**: AIBA_FAILURE_CASE_APPENDIX_S289
**EAG**: EAG-S287-RUNTIME-STABILIZE-001 (조건 3 이행) / EAG-S289-KPI-MEASURE-001
**작성 세션**: S289 (2026-06-26)
**근거**: 가동 중인 `aiba_jeni_runtime.py` v4.11.1 / `aiba_domi_runtime.py` v1.6.0 실측 코드
**검증 상태**: COST_LOG 토큰 역산 정합성 PASE ($0.0142 일치), /health 가드 플래그 active 확인

---

## 1. 목적

S287 런타임 안정화에서 도입된 두 종류의 자동 안전 장치 — **Circuit Breaker**(연속 동일 오류 차단)와 **Budget Block**(일일 예산 초과 차단) — 의 발동 조건, 동작, 복구 절차를 실측 코드 기준으로 문서화한다. 이 부록은 향후 장애 발생 시 발동 원인을 추측 없이 판정하기 위한 기준 문서다.

두 장치는 **성격이 다르다**:

| 구분 | Circuit Breaker | Budget Block |
|------|----------------|--------------|
| 목적 | 무한 오류 반복 차단 (운영 안정성) | 비용 폭주 차단 (재무 안전성) |
| 트리거 | 연속 동일 도구 오류 2회 | 당일 누적 비용 ≥ cap |
| 거버넌스 의미 | 검증 실패 (TRUST_READY=FAIL) | 검증 미실행 (인프라 가드) |
| 판정 오인 위험 | 낮음 | **높음 — 별도 표기 필수** |

---

## 2. Circuit Breaker (C-1)

### 2.1 발동 조건

연속으로 **동일 유형의 도구 오류가 2회** 발생하면 즉시 루프를 중단(ABORT)한다.

오류 유형 분류 (`_classify_tool_error`):

| 분류 | 매칭 패턴 | 예시 |
|------|----------|------|
| `FILE_ERROR` | `NOT_A_FILE`, `DENIED` | 디렉토리를 파일로 읽으려는 시도 |
| `AUTH_ERROR` | `PERMISSION`, `403` | 권한 없는 경로 접근 |
| `TIMEOUT` | `TIMEOUT`, `TIMED_OUT` | 도구 응답 시간 초과 |

정상 결과는 빈 문자열(`""`)을 반환하여 카운터를 0으로 리셋한다.

### 2.2 발동 메커니즘

- 도구 오류 유형이 **직전 오류와 동일**하면 카운터 +1
- 유형이 **다르면** 카운터를 1로 리셋(새 유형 시작)
- 카운터가 **2 이상**이면 발동 → `CIRCUIT_BREAKER` 이벤트 로그 + ABORT

핵심: **"연속 + 동일 유형"** 2회. 서로 다른 오류가 번갈아 나면 발동하지 않는다 (예: FILE_ERROR → AUTH_ERROR → FILE_ERROR 는 각각 카운트 1).

### 2.3 발동 시 결과

- 결과: `TRUST_READY = FAIL` (`_make_fail_closed_result`)
- `error = "CIRCUIT_BREAKER_TRIGGERED"`
- detail에 오류 유형 + "Escalate to Caddy" 명시
- 이벤트 로그(JSON Lines): `{"tag":"CIRCUIT_BREAKER","agent":"jeni","round":N,"error_type":"...","count":2,"action":"ABORT"}`

### 2.4 거버넌스 의미

Circuit Breaker 발동은 **검증 실패**로 간주된다. 동일 오류 2회는 에이전트가 스스로 회복할 수 없는 구조적 장애(잘못된 경로, 권한 문제 등)를 의미하므로, 캐디에게 에스컬레이션하여 원인을 진단해야 한다.

### 2.5 Failure Case 예시

- **Case CB-1**: 제니가 존재하지 않는 경로를 read_file → `NOT_A_FILE` → 같은 경로 재시도 → `NOT_A_FILE` (2회) → ABORT. 원인: 경로 오류. 복구: 정확한 경로 재확인.
- **Case CB-2**: 권한 없는 디렉토리 연속 접근 → `403` 2회 → ABORT. 원인: 화이트리스트 미포함 경로. 복구: 허용 경로 확인.

---

## 3. Budget Block (제니 J-2 / 도미 ④)

### 3.1 2단계 예산 가드 구조

| 단계 | 임계값 | 동작 | 로그 태그 |
|------|--------|------|----------|
| WARN | cap의 80% (디폴트 $0.80) | 경고 로그만 (차단 없음) | `BUDGET_WARN` |
| HARD BLOCK | cap (디폴트 $1.00) | 다음 호출 Fail-Closed | `BUDGET_BLOCK` |

cap 값: `MAX_DAILY_USD` (env `AIBA_MAX_DAILY_USD`, 디폴트 1.0)
WARN 임계: `MAX_DAILY_USD_WARN` (디폴트 = cap × 0.8)

### 3.2 발동 조건

- **WARN**: 호출 직후 당일 누적(`daily_total`)이 WARN 임계 도달 시 `BUDGET_WARN` 로그 출력. 검증은 계속 진행.
- **HARD BLOCK**: **다음 검증 루프 진입 시점**에 당일 누적이 cap 이상이면 즉시 차단. 즉, 한도를 넘긴 그 호출은 완료되고, 그 **다음 호출**이 막힌다 (사전 차단 방식).

당일 누적은 UTC 날짜 기준으로 자동 리셋(`_today_str()` 변경 감지).

### 3.3 발동 시 결과 — 거버넌스 오인 방지 (중요)

Budget Block은 **검증 실패가 아니라 검증 미실행**이다. 이를 거버넌스 판정과 혼동하면 안 된다.

- 결과: `VERIFICATION_RUN = FALSE` (`_make_budget_block_result`)
- `error = "DAILY_BUDGET_EXCEEDED"`, `budget_block = True`, `verification_run = False`
- 명시 문구: "제니의 설계 판정이 아니라 인프라 비용 가드에 의한 검증 미실행 상태"
- 이벤트 로그: `{"tag":"BUDGET_BLOCK","agent":"jeni","daily_total":X,"cap":1.0,"action":"FAIL_CLOSED"}`

**핵심 구분**: Circuit Breaker는 `TRUST_READY=FAIL`(제니가 검증한 결과 실패), Budget Block은 `VERIFICATION_RUN=FALSE`(제니가 검증을 아예 안 함). 후자를 설계 반려로 오인하면 정상 설계를 잘못 기각하게 된다.

### 3.4 복구 절차

1. 당일 누적 비용이 cap을 넘긴 원인 확인 (COST_LOG `daily_total` 추적)
2. 예산 한도 조정(`AIBA_MAX_DAILY_USD` 상향) — 단, DEP 승인 필요
3. 또는 UTC 날짜 변경까지 대기 (자동 리셋)
4. 한도 조정 후 검증 재요청

### 3.5 단가 정합성 (INC-S288-001 재발 방지)

Budget Block의 정확도는 **단가 정합성에 직결**된다. 단가가 실제 모델보다 낮게 설정되면 누적이 과소 측정되어 가드가 늦게 발동한다.

**S289 실측 검증 (도미)**:
- 실제 모델: gpt-4o (systemd 유닛 `AIBA_DOMI_MODEL=gpt-4o`)
- 단가: secrets.env `INPUT=2.50 / OUTPUT=10.00` (gpt-4o 기준)
- COST_LOG 역산: input 5119 × $2.50/M + output 140 × $10.00/M = $0.0142 → 기록값 일치 ✅
- 코드 디폴트(0.15/0.60, mini)는 env 오버라이드로 무력화됨 — **코드만 보면 오인하므로 반드시 실주입 env 실측 필요**

**교훈 (메모리 #28)**: 모델·단가는 코드 디폴트가 아니라 ① systemd 유닛 ② secrets.env ③ /health 또는 COST_LOG 역산 — 세 곳을 교차 실측해야 실제 가동값을 확정할 수 있다.

---

## 4. 두 장치의 상호 관계

- 두 장치는 **독립적**으로 작동한다.
- 한 루프 안에서 Budget Block은 **루프 진입 시점**(최우선), Circuit Breaker는 **도구 실행 직후**에 평가된다.
- 따라서 예산 초과 상태에서는 검증 루프 자체가 시작되지 않으므로 Circuit Breaker는 평가되지 않는다.
- 평가 순서: `Budget Block (진입) → SC_FINAL 로드 → 도구 호출 → Circuit Breaker (도구 직후) → 타임아웃 선점`

---

## 5. 운영 KPI 연계

이 부록의 발동 조건은 운영 KPI 측정의 기준이 된다:

| KPI | 목표 | 측정 소스 |
|-----|------|----------|
| CB 발동률 | < 5% | `CIRCUIT_BREAKER` 로그 / 총 호출 |
| Budget Block 발동률 | (관측) | `BUDGET_BLOCK` 로그 |
| 예산 가드 정확도 | 단가 역산 일치 | COST_LOG `est_usd` 역산 |
| 평균 Tool Round | ≤ 3.5 | audit `tool_rounds` 평균 |

---

## 6. 결론

Circuit Breaker와 Budget Block은 모두 S287에서 설계되어 S288에 배포되었으며, S289 실측으로 가동 상태 및 단가 정합성이 확인되었다. 두 장치의 거버넌스 의미는 명확히 구분되어야 한다 — Circuit Breaker는 검증 실패, Budget Block은 검증 미실행이다. 이 구분을 코드 레벨(`TRUST_READY=FAIL` vs `VERIFICATION_RUN=FALSE`)에서 분리한 것이 S288 책임 분리 설계의 핵심이다.

**미해결/후속 관찰**:
- 코드 디폴트 단가(mini)가 여전히 코드에 남아 있어, env 미설정 환경(예: 신규 배포)에서는 과소측정 위험. 디폴트를 gpt-4o로 올리거나 env 필수화(미설정 시 기동 거부) 검토를 S290+ 의제로 제안.
