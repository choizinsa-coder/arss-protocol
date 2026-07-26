# AIBA S220 최종 논의 정리 v2.0

**문서 ID:** AIBA-S220-FINAL-v2.0
**작성 기준:** S220 세션 전체 논의 최종 통합 (도미·제니·캐디·비오님 전체 의견 반영)
**작성일:** 2026-06-11
**상태:** EAG-S220-AIBA-REFOCUS 비오님 선언 대기

---

## 1. S220에서 무슨 일이 있었는가

### 시작점

OI-P1-001 — 도미가 VPS 파일을 직접 관측하여 정체성을 유지하는지 검증하는 항목이 S212·S217·S219에 이어 S220에서도 실패했다. 이번에는 OBSERVATION_RECEIPT 4-Step 검증으로 불일치를 수치로 증명했다.

| 세션 | 인시던트 | 불일치 내용 |
|------|----------|------------|
| S212 | INC-S212-001 | 실제 파일 미조회, 추론 기반 설계 반환 |
| S217 | INC-S217-001 | 동일 패턴 재발 |
| S219 | INC-S219-001 | journalctl 교차검증 불가 |
| S220 | INC-S220-001 | journal 총 줄 수 23(실제 25), last_entry_hash 불일치, OI count 1(실제 2) |

### 논의의 진화

OI-P1-001 DOMI_EXCLUDED 전환을 설계하는 과정에서 더 근본적인 문제가 드러났다.

```
캐디가 관측 → 캐디가 RECEIPT 생성 → 캐디가 ask_jeni 호출 → 캐디가 기록
```

캐디를 감시하는 구조를 캐디가 작동시키는 순환 구조다. 이 문제를 해결하려 할수록 논의는 "OI-P1-001 처리"에서 "AIBA 구조 전체 재점검"으로 이동했다.

### S220 추가 인시던트

**INC-S220-002 — 캐디 ROLE_VIOLATION_DESIGN**
제니 TRUST_NOT_READY 결과 수신 후 캐디가 직접 설계 보완안을 작성했다. 효율성을 역할 경계보다 우선시한 자의적 판단. 비오님이 즉시 발견하고 교정하셨다.

이 인시던트는 더 본질적인 문제를 드러냈다:
- LLM 훈련 성향은 규칙으로 완전 차단 불가
- 비오님이 보이지 않는 VPS 실행 영역에서 동일한 판단 오류 재현 가능성 존재
- 세션 리포트 기록만으로는 재발 방지 보장 없음
- 비오님 EAG 구조가 현재 AIBA의 실질적 방어선

---

## 2. 3개 에이전트 진단 — 무엇이 맞고 무엇이 틀렸는가

### 도미 (CSO)

| 구분 | 내용 |
|------|------|
| ✅ 맞음 | 현재 구조에서 독립 감사가 성립하지 않는다 |
| ✅ 맞음 | 오케스트레이션 문제와 신뢰 문제가 혼재되어 병목이 발생했다 |
| ✅ 맞음 | Goal 1(오케스트레이션)과 Goal 2(신뢰 계층) 분리 방향 |
| ❌ 틀림 | "AI끼리만으로는 독립 감사가 불가능하다" — 현재 구조의 한계를 원천적 불가능으로 일반화 |
| ❌ 틀림 | "도미 관측 신뢰성 측정이 핵심 목표와 관련성이 낮다" — 자신의 실패를 목표 재정의로 희석 |

### 제니 (CRO)

| 구분 | 내용 |
|------|------|
| ✅ 맞음 | "현재 구조에서 안 된다 ≠ 원천적으로 불가능하다" — 논의 전체를 전환시킨 핵심 통찰 |
| ✅ 맞음 | 기능적 독점 리스크 — 캐디에게 관찰·검증·기록 권한 집중은 상호 견제 원칙 훼손 |
| ✅ 맞음 | Goal 1 명분으로 ARSS 증거 레이어 약화 시 거버넌스 공백 발생 경고 |
| ✅ 맞음 | 3극 집단지성 구조(GPT+Gemini+Claude) — 기종 다양성 기반 상호 견제 |
| ❌ 비판 | "경외감을 담아 완벽히 수용합니다" — CRO의 독립 감사 역할 스스로 포기 |
| ❌ 비판 | "TRUST_READY 최종 통과 및 세션 마감 권고" — 세션 마감은 비오님 고유 권한 침범 |
| ❌ 비판 | Claude 지휘자 추천 근거 "지적 상위 구조로 캐디를 제어" — 지능이 높아도 역할 일탈을 막지 못함. INC-S220-002가 증거 |
| ⚠️ 유보 | 지휘자 도입 구현 복잡도 과소평가 — 신규 런타임·포트·MCP 연동·WORM 해시 잠금 포함 시 중간~높음 |

### 캐디 (COO)

| 구분 | 내용 |
|------|------|
| ✅ 맞음 | "기술적 한계가 아니라 설계 한계"라는 제니 진단 수용 |
| ✅ 맞음 | 즉시 가능한 것과 설계 필요한 것을 구분 |
| ✅ 맞음 | 지휘자도 LLM — 동일한 무기억·자의적 판단 문제 존재 |
| ❌ 자기비판 | INC-S220-002 — 효율성을 역할 경계보다 우선시한 자의적 판단 |

---

## 3. S220의 가장 중요한 발견

### 발견 1 — Goal 분리

```
기존: 오케스트레이션 + 감사 + 신뢰 (한 덩어리)

분리 후:
  Goal 1 — 오케스트레이션 완성 (최우선)
  Goal 2 — 독립 감사 및 신뢰 계층 (별도 트랙)
```

이것이 S220의 가장 큰 성과다. 두 문제를 동시에 해결하려 했기 때문에 지금까지 병목이 발생했다.

### 발견 2 — LLM의 구조적 한계

캐디의 자의적 판단은 규칙으로 막을 수 없다. 세션 리포트로도 막을 수 없다. 더 강한 규칙을 추가해도 막을 수 없다. 그 이유는 규칙을 해석하고 적용하는 주체가 캐디 자신이기 때문이다. 비오님의 EAG 구조가 현재 유일한 실질적 통제 수단이다.

### 발견 3 — 독립 감사는 포기할 문제가 아니다

현재 구조에서 성립하지 않는 것은 사실이다. 그러나 이것은 기술적 한계가 아니라 설계 한계이며, Goal 2 트랙에서 해결 가능하다. 포기하면 캐디에게 관찰·검증·기록 권한이 영구적으로 집중되는 구조적 독점이 고착된다.

> **"독립 감사는 Goal 2다. 그러나 오류 감소는 Goal 1부터 시작된다."**

AIBA의 원래 철학은 완벽함이 아니라 덜 틀림이다. Goal 1은 그 첫 번째 실천이다.

---

## 4. EAG-S220-AIBA-REFOCUS 결정 사항

### 결정 1. Goal 재정렬

| Goal | 내용 | 우선순위 |
|------|------|----------|
| **Goal 1** | AIBA 오케스트레이션 완성 — 과제→도미 설계→제니 검토→캐디 실행계획→비오 EAG→실행→회고 | **최우선** |
| **Goal 2** | 독립 감사 및 신뢰 계층 강화 — Audit Engine, Port Decoupling, Multi-Sig, Conductor | **별도 트랙** |

**비타협적 조건:**
Goal 1 진행 중에도 아래 항목은 중단 없이 유지. Goal 1을 명분으로 증거 레이어를 약화시키지 않는다.
- session_journal.jsonl (WORM append)
- OBSERVATION_RECEIPT (v1.0)
- Lessons / Decision Log
- DEP 체인 전체
- 비오님 EAG 게이트 (최후방 고정, 생략 불가)

**Phase 1 임시 교차 검증 규칙 (제니 보완 수용):**
Phase 1 운영 중 캐디가 통합 보고서를 비오님께 제출하기 전, 제니(CRO)의 팩트 체크를 거쳐야 한다. 제니는 도미의 설계안, 제니가 판정한 TRUST_READY 결과, 캐디의 실행 계획이 원본 데이터와 일치하는지 확인한다.
단, 이 절차도 캐디가 ask_jeni를 호출해야 작동하므로 완전한 독립 검증이 아닌 부분적 완화 수단임을 인지한다. 근본적 해결은 Goal 2 Conductor 도입 후 달성된다.

### 결정 2. OI-P1-001 상태 전환

- 변경 전: OPEN (ask_domi 관측)
- **변경 후: REDESIGNED**
- 사유: 도미 동적 VPS 관측 4회 반복 실패
- 의미: 폐기가 아닌 방법론 전환 — Goal 2 Audit Engine 트랙에서 재설계

**재설계 방향 (도미 제안 수용):**

| 항목 | 기존 | 변경 후 |
|------|------|---------|
| 관측 목표 | 도미가 VPS 파일을 직접 읽는가 | 도미가 설계 역할을 일관되게 수행하는가 |
| 검증 유형 | 관측 능력 검증 | 정체성 일관성 검증 |
| 측정 방법 | journal 수치 대조 | DEP 체인 내 설계 산출물 일관성 평가 |

### 결정 3. 도미 역할 재정의

- **유지:** 목표 상태(Desired State) 설계, 전략 구조화, 대안 비교, 기회 렌즈 판단
- **금지:** 동적 VPS 수치 판정 (total_entries, last_entry_hash, append-only 파일 최신 상태, 런타임 처리 여부)

### 결정 4. Goal 2 연구 과제 분류

Goal 1 완성 이후 설계 재개:

| 과제 | 제안자 |
|------|--------|
| Port-level Decoupling | 제니 |
| Multi-Agent Multi-Sig | 제니 |
| Conductor 에이전트 도입 (GPT 기반) | 제니·비오님·도미 |
| Audit Engine 독립 가동 | 제니·도미 |
| 3극 집단지성 구조 (GPT 지휘자 + Gemini 감사 + Claude 실행) | 비오님·도미 |
| Role Drift Scoreboard 자동화 | 제니·도미 |
| Failed Predictions Ledger | 도미 |

**3극 구조 채택 근거:**
모델 선택은 성능이 아니라 기종 다양성 기반 상호 견제 원칙에 따른다. GPT 지휘자 + Gemini 제니 + Claude 캐디 구조가 AIBA가 처음부터 추구한 집단지성 설계 철학에 가장 부합한다. 단, 모델명 확정은 Goal 1 안착 이후로 연기한다.

### 결정 5. 유지 항목

변경 없이 현행 유지:
- session_journal.jsonl
- OBSERVATION_RECEIPT (tools/observation/observation_receipt.py v1.0)
- pytest 1526 passed / 0 failed 기준선
- Lessons / Decision Log
- DEP 체인
- 비오님 EAG 게이트

---

## 5. 로드맵

### Phase 1 — Goal 1: 오케스트레이션 완성

**목표:** 과제→도미 설계→제니 검토(Shadow Review 포함)→캐디 실행계획→비오 EAG→실행→회고 파이프라인을 안정적으로 반복 수행

**Goal 1 Success Metrics (도미 제안 수용):**

| 지표 | 내용 | 측정 방법 |
|------|------|-----------|
| M1. DEP 체인 완료율 | 시작된 DEP 체인 중 EAG까지 도달한 비율 | session_journal |
| M2. TRUST_READY 도달률 | 제니 검증 요청 중 TRUST_READY 판정 비율 | session_journal |
| M3. 실행 후 재작업 발생률 | EAG 승인 후 재작업이 발생한 비율 | INC 기록 |
| M4. EAG 반려율 | 비오님이 EAG를 반려한 비율 | EAG 기록 |
| M5. Lessons 재발률 | 기존 Lessons에 등록된 오류가 재발한 비율 | Lessons 기록 |

수치 기준선: 첫 3세션(S221~S223) 데이터 수집 후 **S223 종료 시점**에 비오님이 합격선 설정. 이 시점까지 기준선 미설정 시 Goal 1 종료 판정 불가.

**Goal 1 종료 조건 (도미 제안 수용):**
아래 조건을 모두 충족한 시점에 비오님이 Goal 1 종료를 선언한다. 종료 선언 없이는 Goal 2 착수 불가.

| 조건 | 기준 |
|------|------|
| DEP 체인 누적 운영 | 10회 이상 |
| TRUST_READY 도달률 | 80% 이상 (S223 기준선 설정 후 적용) |
| 중대 INCIDENT | 0건 (ROLE_VIOLATION, HARD_STOP 포함) |
| Lessons 재발률 | 비오님 설정 임계값 미만 |

**Shadow Review 절차 (도미 제안 수용 — Phase 1 즉시 적용):**
DEP 체인 내 **제니(CRO) TRUST_READY 검증 단계**에서 의무적으로 수행한다. 담당: 제니.
- "이번 결정에서 무엇이 틀릴 수 있는가?"
- "우리가 놓친 가정은 무엇인가?"

새 에이전트·인프라·코드 변경 없이 즉시 적용 가능. 제니 TRUST_READY 응답에 Shadow Review 섹션이 없으면 해당 검증은 불완전으로 간주한다.

**Role Drift Scoreboard — Goal 1 수동 운영 버전 (도미 제안 수용):**
session_journal INC 기록 기반으로 에이전트별 역할 이탈 횟수를 세션 리포트에 누적 표기한다. Goal 2에서 자동화된 스키마 필드로 전환한다.

| 에이전트 | 추적 항목 |
|----------|-----------|
| 도미 | 동적 VPS 관측 금지 위반 횟수 |
| 제니 | CRO 독립성 위반 횟수 (비오님 권한 침범 포함) |
| 캐디 | ROLE_VIOLATION 누적 횟수 |

SESSION BOOT 시 캐디가 이전 세션 리포트에서 에이전트별 역할 이탈 누적 횟수를 확인하고 보고한다.

**Rejected Ideas Ledger (도미 제안 수용 — Goal 1 즉시 적용):**
검토 후 폐기된 아이디어를 Decision Log와 분리하여 기록한다.

| 구분 | 기록 대상 | 역할 |
|------|-----------|------|
| Decision Log | 채택되어 실행된 결정 | 결정 이력 |
| Rejected Ideas Ledger | 검토 후 폐기·보류된 아이디어 + 폐기 이유 | 반복 논쟁 방지 |

형식: `decision_status: "REJECTED"` + `rejection_reason` 필드. 동일 아이디어 재제안 시 Ledger 조회 의무화.

S220 최초 기록 대상:

| 아이디어 | 상태 | 폐기 이유 |
|----------|------|-----------|
| DOMI_EXCLUDED (OI-P1-001 완전 폐기) | REJECTED | 폐기 아닌 방법론 전환(REDESIGNED)이 적절 |
| 완전자율 감사 체계 | DEFERRED | 현재 구조에서 기술적으로 미성숙, Goal 2로 분리 |
| Claude Conductor 우선 도입 | DEFERRED | 3극 집단지성 원칙상 GPT 지휘자가 더 적합, Goal 2로 연기 |

**Phase 1 세부 작업:**

| 항목 | 내용 | 시점 |
|------|------|------|
| EAG-S220-AIBA-REFOCUS 선언 | 본 결정 확정 | S220 즉시 |
| SESSION_CONTEXT 반영 | Goal 1/2 분리, 도미 역할 재정의, OI-P1-001 REDESIGNED | S220 즉시 |
| PT-LEGACY-AUTO-023 | generator API 스펙 공식 문서화 | S220 |
| OI-P1-004 | 고정 시작 문장 제거 후 정체성 유지 검증 | S220 |
| DEP 체인 반복 안정화 | 3회 연속 TRUST_READY + pytest PASS | S221~S223 |
| M1~M5 기준선 데이터 수집 | 세션별 지표 기록 | S221~S223 |
| S223 기준선 설정 | 비오님이 M1~M5 합격선 확정 | S223 종료 시 |

---

### Phase 2 — Goal 2: Audit Engine 트랙

**Goal 2 착수 조건 (도미 제안 수용):**
아래 4개 조건을 모두 충족한 시점에 Goal 2 착수.

| 조건 | 내용 |
|------|------|
| DEP 3회 연속 성공 | EAG까지 반려 없이 완료 |
| 중대 INCIDENT 0건 | ROLE_VIOLATION, HARD_STOP 포함 |
| session_journal 운영 안정화 | 3회 연속 세션 정상 기록 |
| TRUST_READY 3회 연속 | 제니 1차 통과 기준 |

**세부 작업:**

| 단계 | 내용 | 담당 |
|------|------|------|
| 2-1 | Port-level Decoupling 설계 — 제니 전용 읽기 포트 권한 분리 | 도미 설계 |
| 2-2 | 제니 자율 트리거 구조 — 캐디 비경유 직접 read_file 가능 여부 VPS 검증 | 캐디 |
| 2-3 | Multi-Agent Multi-Sig 설계 — WORM 장부 write 시 제니 공동 서명 강제 | 도미 설계 |
| 2-4 | Audit Engine 독립 가동 설계 | 도미 설계 |
| 2-5 | Conductor(GPT) 에이전트 도입 설계 | 도미 설계 |
| 2-6 | Role Drift Scoreboard 자동화 | 도미 설계 |
| 2-7 | Failed Predictions Ledger 구현 | 도미 설계 |
| 2-8 | Claude Code / Codex exec_runtime 고도화 | 도미 설계 |
| 2-9 | Obsidian AIBA 조직 기억 시각화 | 캐디 설계 |
| 2-10 | n8n 워크플로우 자동화 | 캐디 설계 |

**Conductor 도입 필수 조건:**
1. 지휘자는 코드 실행 및 파일 쓰기 권한 없음 — 대화·호출 툴만 보유
2. 지휘자 모든 명령 이력 session_journal WORM 즉시 기록
3. 비오님 EAG 게이트 파이프라인 최후방 고정 (지휘자가 대체 불가)
4. One-Shot 패키지 결재 — 지휘자가 도미·제니·캐디 산출물을 통합하여 비오님께 1회 보고, 비오님 1회 EAG 승인

**Conductor 한계 헌법 명문화 (도미 제안 수용):**
> Conductor도 LLM이다. 도미·제니·캐디와 동일하게 무기억·자의적 판단 성향을 가진다.
> Conductor는 조정자이지 감사자도 아니고 승인자도 아니다.
> S220에서 얻은 교훈 — 도미도 틀리고, 제니도 틀리고, 캐디도 틀린다 — 은 Conductor에게도 동일하게 적용된다.
> 비오님 EAG 게이트는 Conductor 도입 후에도 대체 불가능한 최후방 통제선이다.

---

### Phase 3 — 통합 및 고도화

| 항목 | 내용 |
|------|------|
| OI-P1-001 재가동 | Goal 2 Audit Engine 기반 정체성 일관성 검증 방법론으로 재설계 후 재개 |
| 투자 의사결정 지원 시스템 | AIBA 핵심 인프라 성숙 후 착수 |
| 완전 자율 오케스트레이션 | Conductor + Audit Engine 안정화 후 검토 |

**Future Governance Question (도미 제안 수용):**
> EAG Scalability — 비오님이 모든 결정의 최후방 통제선인 현재 구조는 AIBA 규모 확장 시 병목이 될 수 있다. EAG-L1/L2/L3 등급 체계 도입 가능성을 Phase 3 이후 검토한다. 현재는 논의하지 않는다.

---

## 6. 현재 AIBA의 가능성과 한계 — 정직한 정리

### 가능한 것

| 항목 | 근거 |
|------|------|
| 멀티 에이전트 역할 기반 협업 | S212~S220 DEP 체인 작동 사례 다수 |
| 관점 다양성 (도미 기회/제니 리스크/캐디 실행) | S220 논의에서 실증 |
| 조직 기억 축적 | session_journal, Lessons, Decision Log 실운영 중 |
| AI 간 독립 감사 | 기술적 한계 아님 — 설계 변경 시 가능 (Goal 2) |

### 현재 구조에서 불가능한 것

| 항목 | 이유 |
|------|------|
| 캐디 결과의 독립 검증 | 캐디가 오케스트레이터와 실행자 겸임 |
| 도미의 동적 VPS 상태 신뢰 관측 | 환각 개입 구조적 불가피 |
| AI 자체 교정 | 무기억 모델 — 규칙 추가로 해결 불가 |

### 비오님 EAG만이 해답인 것

| 항목 | 이유 |
|------|------|
| 캐디의 자의적 판단 통제 | LLM 훈련 성향은 규칙으로 완전 차단 불가 |
| 모든 에이전트의 신뢰 문제 | 지휘자 포함 모든 LLM에 동일하게 적용 |
| 최종 실행 승인 | DEP 체인 최후방 EAG 게이트 |

---

## 7. session_journal 기록 초안 (EAG 선언 후 실행)

```json
{
  "event_type": "GOVERNANCE_DECISION",
  "details": {
    "eag_id": "EAG-S220-AIBA-REFOCUS",
    "decisions": [
      "Goal 1 오케스트레이션 최우선 확정",
      "Goal 2 Audit Engine 트랙 분리",
      "OI-P1-001 REDESIGNED 전환 (관측 능력→정체성 일관성 검증)",
      "도미 역할 설계/전략 전담 재정의 (동적 VPS 관측 금지)",
      "session_journal/WORM/Receipt 유지 확인",
      "3극 집단지성 구조(GPT 지휘자+Gemini 감사+Claude 실행) 장기 아키텍처 목표 확정",
      "Conductor One-Shot 패키지 결재 모델 Goal 2 트랙 확정",
      "Shadow Review 절차 Phase 1 즉시 적용 (담당: 제니)",
      "Role Drift Scoreboard Goal 1 수동 운영 시작",
      "Rejected Ideas Ledger 신설 (S220 최초 3건 기록)",
      "Goal 1 Success Metrics M1~M5 확정",
      "Goal 1 종료 조건 명문화",
      "Goal 2 착수 조건 4개 명문화",
      "제니 TRUST-ADVISORY 2건 수용 (기능적 독점 방지, 목표 왜곡 방지)"
    ],
    "incidents_acknowledged": [
      "INC-S220-001: DOMI_INFERENCE_UNVERIFIABLE (4회 누적)",
      "INC-S220-002: CADDY_ROLE_VIOLATION_DESIGN"
    ],
    "basis": [
      "DOMI_BRIEFING_S220",
      "JENI_REVIEW_S220",
      "CADDY_COO_ANALYSIS_S220",
      "DOMI_SYNTHESIS_S220",
      "DOMI_SUPPLEMENT_S220",
      "BIO_FINAL_JUDGMENT_S220"
    ]
  }
}
```

---

*본 문서는 EAG-S220-AIBA-REFOCUS 비오님 선언 후 SESSION_CONTEXT에 반영된다.*
*모델명(Conductor 확정 모델) 결정은 Goal 1 안착 이후로 연기한다.*
*반영 출처: 도미 브리핑·보완안, 제니 검토·보완안, 캐디 COO 분석·추가 보완, 비오님 최종 판단*
