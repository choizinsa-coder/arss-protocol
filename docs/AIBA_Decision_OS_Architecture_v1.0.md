# AIBA Decision OS Architecture v1.0
## Knowledge-Driven Decision Operating System — Living Constitution

**문서 상태:** v1.0 (헌법 지위, EAG 승인 후 govdoc_freeze_gate 등록 대상)
**작성 기준:** S322 전략 토론 전 라운드 통합 + 비오님 핵심 지시 반영
**작성일:** 2026-07-03
**이전 버전:** v0.3 → v1.0 (Section 16-17 신규, 상시 운영 원칙 추가)

---

## 이 문서의 위치

```
AIBA Manifesto (2페이지, 불변) ← 이 문서에서 추출 예정
        ↓
AIBA Decision OS Architecture v1.0  ← 이 문서 (헌법)
        ↓
AIF Area Specifications (Area 1, 6, 7, 10, 11, 13, 15 등)
        ↓
Session Records (SESSION_CONTEXT_S{n}_FINAL.json)
```

**PROJECT INSTRUCTIONS(CADDY v3.9)와의 관계:**
PROJECT INSTRUCTIONS는 캐디의 운영 규칙이며 이 문서와 별개 레이어다.

**SESSION_CONTEXT와의 경계:**
SESSION_CONTEXT는 세션 단위 운영 기록(무엇을 했는가). Knowledge Graph는 세션을 가로지르는 전략 지식(왜 그 결정을 했는가). 두 시스템은 Decision 노드(Area 11)를 통해 연결된다.

---

## Non-Goals (AIBA가 하지 않는 것)

1. AIBA는 AI 모델을 대체하지 않는다.
2. AIBA는 AI의 내부 추론을 복원하려 하지 않는다.
3. AIBA는 모든 결정을 자동화하지 않는다. 최종 책임은 Sovereign(비오님 EAG)에 남는다.
4. AIBA는 데이터를 창작하지 않는다. 기록하고 검증하고 연결한다.
5. AIBA는 단기 효율보다 장기 신뢰를 우선한다.
6. **AIBA는 비오님이 매번 시작 버튼을 눌러야만 작동하는 도구가 아니다. 감시는 상시적이며, 임계값을 넘으면 시스템이 먼저 알린다. 비오님은 모든 시작이 아니라 방향과 한계를 결정하는 존재다.**
7. **모든 KPI는 건강 상태를 관찰하기 위한 신호이며, KPI 자체를 목표로 최적화하는 행위는 거버넌스 위반이다.** GHS 점수를 높이기 위해 실패 기록을 누락하거나 Calibration 데이터를 왜곡하는 행위를 포함한다.
8. **AIBA는 모든 지식을 영구 보존하지 않는다.** 가치가 소멸된 지식은 은퇴(Retirement) 처리하여 현재 의사결정을 오염시키지 않는다. 기억과 망각은 모두 거버넌스의 일부다.

---

## 핵심 명제

> **AIBA는 AI 에이전트 도구가 아니다. 조직이 올바른 결정을 내리는 전 과정을 관리하고, 같은 실수를 반복하지 않도록 기억하며, 비오님이 자리를 비워도 감시는 멈추지 않고, 임계값이 넘으면 스스로 알리고 사전 승인된 조건 하에 착수하는 Decision Operating System이다.**

---

## 1. 전체 아키텍처: 5개 계층

```
┌─────────────────────────────────────────────────────┐
│  Layer 5: Meta Governance Layer (SIM)               │
│  System Integrity Monitor — 레이어 자체를 감시      │
│  GHS 측정, 개선 제안 자동 생성                      │
├─────────────────────────────────────────────────────┤
│  Layer 4: Presentation Layer                        │
│  Kanban Board / Ledger Views / Dashboard / Alert    │
│  (Graph를 보여주는 UI — 데이터 모델 아님)           │
├─────────────────────────────────────────────────────┤
│  Layer 3: Operation Layer                           │
│  Agent Dispatch / Work Graph / Ready Queue          │
│  aiba-monitor.service / 상시 감시                  │
├─────────────────────────────────────────────────────┤
│  Layer 2: Decision Layer                            │
│  Decision Quality / Organizational Adaptation       │
│  Recursive Self-Improvement Engine (Area 7)         │
├─────────────────────────────────────────────────────┤
│  Layer 1: Knowledge Layer                           │
│  Knowledge Graph / Evidence / Assumption / Signal   │
└─────────────────────────────────────────────────────┘
```

**Graph vs Ledger 원칙:**
내부 저장 구조는 Knowledge Graph. 사용자가 보는 Ledger, Kanban은 그래프의 투영(View)이다.

---

## 2. 핵심 철학

### 2.1 Trust Infrastructure

고객이 사는 것은 "거버넌스"가 아니라 "AI를 안심하고 사용할 수 있는 능력"이다.
```
ARSS → Governance → Trust Infrastructure → Business Enablement
```

### 2.2 반복 방지 > 학습

담당자가 교체되면 같은 실수가 반복된다. AIBA의 목표는 "더 똑똑해지는 시스템"보다 **"같은 실수를 하지 않는 시스템"**이다. Area 15(Failure Memory)가 이 철학의 물리적 구현이다.

### 2.3 Luck vs Skill 분리와 VEV

Outcome = Skill Component + Luck Component

**VEV 원칙**: "운"으로 분류하려면 결정 시점에 사전 선언된 VEV가 있어야 한다. 사후 발견 변수는 `posthoc_external_factor`로 기록만 하되 면책에 사용 불가.

### 2.4 상시 운영 원칙 (Always-On Principle) — 신규

**MONITOR와 EXECUTE는 분리된다.**

- **항상 돌아가는 것**: 감지, 분석, 준비, 알림
- **비오님 승인이 필요한 것**: 실행, 방향 결정, EAG 승인

비오님은 모든 시작 버튼이 아니라 **방향과 한계**를 결정한다. 시스템은 비오님이 자리를 비워도 감시를 멈추지 않는다.

### 2.5 구조 원칙 3가지

**Evidence-First**: 모든 결정은 검증된 증거에서 시작한다.

**Fail-Safe-First**: 60~100% 정상 → 30~60% 경보+작업계속 → 0~30% Fail-Closed. 즉시 전면 차단 없음.

**Retirement-Aware**: 모든 지식에는 생성과 은퇴가 있다.

---

## 3. Knowledge Graph 사양

### 3.1 전체 그래프 구조

```
Observation
     │
     ▼
Evidence [Evidence_Confidence + Inference_Confidence]
     │
     ├────────────────────────────┐
     ▼                            ▼
  Signal [5-tier]          Assumption Graph
     │                     [신뢰도+TTL+의존관계+VEV]
     └──────────┬──────────────────┘
                ▼
          Opportunity [Score + Freshness + Reversibility]
                │
                ├──► Rejected Opportunity [shattering_trigger]
                │
                ▼
     [Pre-Mortem Gate if required]
                │
                ▼
          Decision ──── [EAG + Area 11 + Sovereign Veto]
                │
                ├──► WorkItem(domi, DESIGN)
                ├──► WorkItem(jeni, VERIFY)
                ├──► WorkItem(caddy, IMPLEMENT)
                └──► WorkItem(beo, EAG)
                           │
                           ▼
                        Task → Outcome
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼             ▼
                 Learning    Failure      Assumption
                 (Area 13)   (Area 15)    Shattering
                    │            │
                    └────────────┘
                    Area 7: Recursive Self-Improvement
```

### 3.2 모든 노드의 공통 속성

```json
{
  "id": "고유 ID",
  "type": "Evidence | Assumption | Opportunity | Decision | WorkItem | ...",
  "created_at": "ISO timestamp",
  "created_by": "actor_id (Area 9 AICS 검증)",
  "evidence_confidence": "0.0~1.0",
  "inference_confidence": "0.0~1.0",
  "expires_at": "ISO timestamp (TTL)",
  "source_hash": "SHA-256",
  "references": ["node_id"],
  "eag": "EAG-ID",
  "status": "active | stale | quarantine | verified | rejected | retired",
  "retirement": {"retired_at": null, "reason": null, "outcome_summary": null}
}
```

---

## 4. 노드 유형 상세

### 4.1 Observation vs Signal

| 구분 | 정의 | 예시 |
|-----|-----|-----|
| Observation | 가공되지 않은 사실 | "OpenAI, o3 모델 발표" |
| Signal | 해석된 의미 | "AI Agent 시장 성장 가속" |

### 4.2 Signal 5단계 + Coordinated Influence 방어

| 등급 | 의미 | 처리 |
|-----|-----|-----|
| Verified | 1차 출처 + 해시 바인딩 | 즉시 사용 |
| Likely | 신뢰 2차 출처 | 조건부 사용 |
| Unknown | 출처 불명 | Quarantine |
| Questionable | 상충 정보 존재 | 별도 검증 |
| Rejected | 위조/환각 | 즉시 폐기 |

독립 1차 출처 2개 미만 → `Questionable` 제한. `Signal_Trust = Count × Independence × Diversity`

### 4.3 Evidence + 신뢰도 분리

Evidence_Confidence (데이터 품질) ≠ Inference_Confidence (추론 품질). 낮은 쪽에 따라 다른 처방이 나온다.

### 4.4 Assumption Graph + VEV + Belief Revision

의존관계 그래프 구조. 상위 가정 신뢰도 하락 시 하위 노드 자동 재계산.

Belief Revision: 새 Ledger 없이 Assumption 노드의 생애주기 이벤트로 처리.

```json
{
  "belief_revision_events": [
    {"revised_at": "2026-10-01", "previous_confidence": 0.92, "new_confidence": 0.75,
     "reason": "시행 연기 가능성", "evidence_ref": "E-045"}
  ]
}
```

### 4.5 신뢰도 전파 3단계

| 구간 | 상태 | 처리 |
|-----|-----|-----|
| 60~100% | 정상 | 운영 계속 |
| 30~60% | 경보 | 경보 + 작업 계속 |
| 0~30% | Fail-Closed | Sovereign Override Gate 발동 가능 |

### 4.6 TTL/시간 소멸

| 유형 | TTL |
|-----|-----|
| 규제 동향 | 6개월 |
| 시장 데이터 | 3개월 |
| 기술 트렌드 | 1개월 |
| 경쟁사 동향 | 2주 |

Stale 노드는 신규 가설 엔진에서 물리적 격리. 읽기 전용 아카이브로 이동.

### 4.7 Opportunity Score 공식

```
Opportunity Score =
  (Expected_Value
   × Evidence_Confidence × Inference_Confidence
   × Freshness_Factor
   × Strategic_Alignment_Mission  [비오님 전용]
   × Operational_Alignment        [시스템 자동]
   × Capability_Fit               [3자 교차검증, min()]
  )
  / (Validate_Cost × Wrong_Cost_Factor × Reversibility_Penalty)
```

`Freshness_Factor`: 비선형, 신호 유형에 따라 증가/감소 가능.
`Capability_Fit = min(Tech, People, Funding, Partner, Time)`. 3자 교차검증(도미 요구→캐디 가용→제니 Gap).

### 4.8 Counter-Hypothesis Loop

기각된 기회의 근거 가정이 무너지면 자동 재활성화 + 레이더 가중치 업데이트.

### 4.9 Retirement 생명주기

Opportunity → 성공 → Archive / 실패 → Area 15
Assumption → 검증됨 / 무효화 → Retired

### 4.10 WorkItem 노드

```json
{
  "type": "WorkItem",
  "parent_decision": "D-089",
  "actor": "domi | jeni | caddy | beo | external",
  "work_type": "DESIGN | VERIFY | IMPLEMENT | TEST | EAG | REVIEW",
  "status": "waiting | ready | in_progress | done | blocked",
  "depends_on": ["WI-001"],
  "sla_deadline": "ISO timestamp",
  "escalate_at": "ISO timestamp",
  "wf05_task_id": "WF-05 연동 ID"
}
```

### 4.11 Conflict Resolution (3유형)

| 유형 | 해소 |
|-----|-----|
| Evidence-Evidence | 제3 독립 출처 탐색 |
| Assumption-Assumption | Pre-Mortem → 도미 조정 → 제니 검증 |
| Assumption-Outcome | Area 13 Calibration 즉시 트리거 |

30일 미해소 → 비오님 EAG 자동 에스컬레이션.

### 4.12 Challenge/Appeal, Sovereign Veto Event

Challenge: 기존 판단에 이의 제기 가능.
Sovereign Veto Event: 비오님 거부 시 최소 사유 기록 → Area 13 지도학습 데이터.

---

## 5. Decision Quality Framework

### 5.1 5개 차원

```
Decision Quality = Evidence_Quality × Assumption_Validity
                 × Execution_Quality × Outcome_Calibration
                 × Process_Quality
```

Process_Quality: EAG 절차 준수, DEP 체인 완전성. 절차 없는 결정은 Quality 불인정.

### 5.2 Luck/Skill + VEV

Skill(통제 가능) vs Luck(사전 선언된 VEV 발생 시만 인정). 사후 발견 외부 변수: 기록만, 면책 불가.

### 5.3 Reversibility 메타데이터

| Reversibility | Wrong_Cost_Factor |
|---|---|
| HIGH (Two-way) | 그대로 |
| MEDIUM | 1.5배 |
| LOW (One-way) | 지수적 증폭 + 자동 승인 트랙 원천 배제 |

### 5.4 Confidence Calibration + Calibration Window

`Calibration_Error = |Predicted_Confidence - Actual_Success_Rate|`

임계 초과 → 모든 자동화 Fail-Closed → 비오님 수동 EAG.

Calibration Window: 편향 기간 발견 시 해당 기간 결정 노드 `calibration_warning: true` 소급 부착.

Area 15 반복 실패 감지 → Area 13 Calibration 재평가 자동 트리거.

---

## 6. Organizational Adaptation Loop

```
Outcome → Learning → Policy Update → Workflow Update
    → Area Update → Architecture Update (EAG 필수) → 운영
```

Architecture Update는 반드시 비오님 EAG를 거친다.

---

## 7. Strategic Alignment 2계층

```
Mission Alignment (비오님 전용, 도메인별 0.0~1.0 설정)
    ×
Operational Alignment (시스템 자동, 현재 자금·일정·역량)
    =
Portfolio Priority
```

2D 벡터: 의사결정 설명 시 두 축을 개별 표기.

---

## 8. 거버넌스 레이어

### 8.1 Area 1 파이프라인

```
외부 신호 수집 → [제니: Signal Verification Gate]
    → Evidence 생성 (해시 바인딩)
    → [도미: 교차 분석 + Assumption Graph]
    → [제니: Compliance Audit]
    → Opportunity (Score 자동 계산)
    → [Pre-Mortem Gate — 조건 충족 시 강제]
    → [제니: Differential EAG 판정]
    ├── Score > 임계 AND Reversibility ≠ LOW AND Wrong_Cost < 임계
    │   → 자동 승인 트랙 (WF-05 Guardian)
    └── 그 외 → 비오님 EAG
    → MVP 검증 → Outcome → 분기
    → Signal Model Update
```

### 8.2 Pre-Mortem Protocol

강제 조건: `Reversibility = LOW` OR `Wrong_Cost_Factor > 임계치`

```
Reversibility = HIGH → 선택
Reversibility = MEDIUM → 간이 (핵심 리스크 1개 이상)
Reversibility = LOW → 정식 필수 (없으면 EAG 제출 차단)
```

### 8.3 I/O Boundary 3단계

```
Public     → Decision + Evidence Summary
Customer   → Decision + Evidence + Reason
Regulator  → Decision + Evidence + Assumption + Audit Trail + Hash
```

Phase 1: RBAC + Audit Trail Hook. Phase 2: Cryptographic Key Release.

### 8.4 Differential EAG

Score > 임계 + Reversibility ≠ LOW + Wrong_Cost < 임계 → 자동 트랙. Area 6/10 담당.

### 8.5 Capability_Fit 3자 교차검증

도미(요구사항) → 캐디(가용성) → 제니(Gap 감사). `Capability_Fit = min(Tech, People, Funding, Partner, Time)`.

---

## 9. Operation Layer (Agent Dispatch / Work Graph)

### 9.1 Ready Queue

Decision 승인 시 WorkItem 자동 생성. Graph 상태 변화가 Workflow를 만들어낸다.

```
Opportunity 승인 → Decision
    → WorkItem(domi, DESIGN, ready)
    → WorkItem(jeni, VERIFY, pending)
    → WorkItem(caddy, IMPLEMENT, pending)
    → WorkItem(beo, EAG, pending)
```

### 9.2 WF-05 연결

WF-05 = WorkItem 소비 실행 엔진. Dispatch Layer = 어떤 WorkItem을 WF-05에 전달할지 결정하는 Coordinator.

### 9.3 Human + AI 통합

```
Ready for Beo (EAG)
Ready for External Expert (도메인 자문)
Ready for Customer Feedback
Ready for Legal Review
```

AIBA는 AI만이 아닌 사람과 AI가 함께 일하는 조직 운영체계다.

### 9.4 Kanban = View

Kanban Board는 Operation Layer의 UI, 데이터 모델이 아니다.

---

## 10. 전체 AIF 연결 사이클

```
Area 1 (Opportunity Intelligence)
    ↓ 기회 발굴
Area 11 (Decision Ledger)
    ↓ 결정 기록 + EAG
aiba-monitor.service (상시 감시)
    ↓ 임계값 감지 → 알림
Operation Layer (WorkItem, Dispatch)
    ↓ 실행 순서
Area 6 (Governance Compiler) + Area 10 (EDS)
    ↓ 실제 실행
Area 5 (Sovereign Authority)
    ↓ Override / Veto
Area 13 (Evaluation — Calibration 포함)
    ↓ 결과 측정
Area 15 (Failure Memory)
    ↓ 반복 실패 감지 → Area 13 트리거
Area 7 (Recursive Self-Improvement — 이 문서의 핵심)
    ↓ GHS 측정 → 개선 제안
Area 9 (AICS — Actor Registry)
    ↓ 모든 actor 인증
Area 1 (Signal Model Update)
    └── 루프 재시작
```

---

## 11. 비즈니스 모델

### 11.1 포지셔닝
```
ARSS → Governance → Trust Infrastructure → Business Enablement
```

### 11.2 첫 번째 고객: CRO
규제 대응 증거 + 이사회 개인 책임 방어가 필요한 최고리스크책임자.

### 11.3 3단계 진입
1단계(1년): AI 컴플라이언스 기록 서비스.
2단계(3년): ARSS 인증 발급. AIBA가 심판이 된다.
3단계(10년): Decision OS. 외부 에이전트가 ARSS Protocol로 합류.

### 11.4 AI 프로젝트 리스크 스코어
Assumption 데이터 누적 → "당신 팀 프로젝트 가정 중 역사적 실패율 높은 유형 포함." 잠재 고객: CRO, VC, AI 배상 보험.

### 11.5 플라이휠
결정 이력은 복사 불가. 이것이 진짜 해자(Moat).

---

## 12. 구현 로드맵

### 12.1 기존 구현 매핑

| 노드 | 기존 구현 |
|-----|---------|
| Decision Ledger | area_11_decision_ledger.py ✅ |
| Sovereign Override | sovereign_authority.py (Area 5) ✅ |
| Failure Memory | area_15_failure_memory.py (Area 15) ✅ |
| Evidence / Assumption / Opportunity | 신규 |
| WorkItem | Phase 1 스키마만 |

### 12.2 Phase 1 MVKG
4개 노드(Evidence, Assumption, Opportunity, Decision) + WorkItem 스키마. 기존 Area 5·11·15를 그래프 노드로 연결. `last_review_date` 필드를 SESSION_CONTEXT에 추가.

### 12.3 Phase 2
Merkle Graph Anchor, Cryptographic Key Release, Confidence Calibration 전체, aiba-monitor.service 본격 구현.

### 12.4 Phase 3
Full ARSS Certification, 외부 에이전트 온보딩, Multi-domain Signal Model.

### 12.5 Phase 1 최소 신뢰 기준
Evidence + Decision + ARSS hash + 불변 저장 = 첫 외부 고객 대응 최소 구성.

---

## 13. 아키텍처 통합

**SESSION_CONTEXT vs Knowledge Graph:**
SESSION_CONTEXT = 세션별 운영 기록. Knowledge Graph = 전략 지식 크로스 세션. 연결 고리 = Area 11 Decision 노드.

**AIF Area 9 Actor Registry:**
Knowledge Graph의 모든 `created_by` 필드는 Area 9(AICS)에서 인증. 외부 에이전트도 Area 9 등록 필수.

---

## 14. 헌법 개정 프로토콜

```
① 3에이전트 합의 (도미 설계 + 제니 검증 + 캐디 구현 검토)
② 비오님 EAG 명시적 승인
③ Backward Compatibility Report (캐디 작성):
     - 영향 받는 Area, Protocol
     - Migration + Rollback 계획
④ git commit hash로 개정 이력 영구 기록
⑤ govdoc_freeze_gate.py FROZEN_HASH 등록
```

Backward Compatibility Report 미제출 개정안 → 제니 `TRUST_NOT_READY` 즉각 차단.

---

## 15. Recursive Self-Improvement Protocol (AIF Area 7)

> **AIBA는 문제가 발생했을 때만 개선하는 시스템이 아니라, 문제가 없어도 정기적으로 자기 자신을 평가하고 개선안을 생성하는 시스템이다. 이 자기개선 루틴은 선택 사항이 아니라 거버넌스의 핵심 의무다.**

### 15.1 개선의 두 가지 유형

**Event-Driven (사건 기반)**: 실패, 임계값 돌파, 외부 변화 → 즉시 트리거
**Time-Driven (시간 기반)**: 정기 스케줄 → 문제 없어도 반드시 실행

둘은 선택이 아니라 병행이다. Time-Driven은 기준선, Event-Driven은 가속 트리거.

### 15.2 정기 Review 스케줄

| 주기 | 내용 | 담당 | 비오님 개입 |
|-----|-----|-----|---------|
| Daily | Area 13 Calibration 수치 자동 집계, Area 15 실패 카운터 | 자동(aiba-monitor.service) | 없음 |
| Weekly | Failure Pattern Audit, Opportunity Freshness 점검 | 캐디 요약 생성 | 확인 |
| Monthly | Assumption Review, Operational Alignment 재계산 | 도미 참여 | EAG |
| Quarterly | Constitution Review Proposal 자동 생성 (GHS 기반) | AI 생성 | 검토/결정 |
| Semi-Annual | Full Architecture Audit | 전 에이전트 | EAG |

### 15.3 5가지 Event Trigger

| 트리거 | 조건 | 자동 행동 |
|-------|-----|---------|
| Failure | Area 15 동일 RC 반복 ≥ 3회 | Area 13 Calibration 재평가 |
| Calibration Drift | Calibration_Error > 임계값 | 자동화 Fail-Closed + 비오님 알림 |
| Mission Drift | GHS.Strategic_Alignment 하락 | Quarterly Review 조기 실행 |
| Opportunity Decay | 6개월 방치 Opportunity 누적 | Opportunity Audit WorkItem 생성 |
| External Change | VEV 감시 대상 외부 변수 발생 | Architecture Review 제안 생성 |

예: EU AI Act 시행령 변경 감지 → Architecture Review Proposal 자동 생성 → 비오님 알림.

### 15.4 Governance Health Score (GHS)

System Integrity Monitor(SIM)가 산출하는 단일 건강 지표.

```
GHS = w1 × (1 - Calibration_Error_Rate)
    + w2 × (1 - Failure_Repeat_Rate)
    + w3 × (1 - Opportunity_Decay_Rate)
    + w4 × Process_Compliance_Rate
    + w5 × Constitution_Adherence_Rate
```

GHS < 임계값 → Constitution Review Proposal 자동 생성 → 비오님 검토 요청.

### 15.5 AI 생성 Constitution Review Proposal

분기별로 또는 GHS 임계값 하락 시 시스템이 자동으로 다음을 생성한다:

1. 지난 기간 GHS 변화 요약
2. 반복 실패 패턴 분석
3. 새로 발견된 패턴
4. 헌법 개정 제안 초안 (3에이전트 합의를 위한 시작점)
5. 예상 영향 범위

이 제안은 비오님이 검토하고 개정 프로토콜을 시작할지 결정한다. AI가 개정을 강제하지 않는다.

### 15.6 Self-Improvement Debt

정기 리뷰가 긴급 작업으로 건너뛰어지면 Self-Improvement Debt가 쌓인다. 부채가 임계값을 넘으면 신규 Feature 작업을 차단하고 리뷰를 먼저 수행한다. "지금 바쁘니까 리뷰는 나중에"를 무한 반복하지 않는 장치.

---

## 16. Always-On Runtime Architecture

### 16.1 핵심 원칙

```
비오님이 자리를 비워도 → 감시는 계속된다
임계값을 넘으면 → 시스템이 먼저 알린다
사전 승인된 조건 충족 시 → 시스템이 착수한다
비오님은 → 방향과 한계를 결정한다
```

### 16.2 aiba-monitor.service

새 systemd 서비스. 5분마다 실행. EAG 불필요 (감시만, 실행 없음).

```
aiba-monitor.service 실행 내용:
    ① GHS 계산 (5개 지표 집계)
    ② 임계값 초과 항목 감지
    ③ 오버듀 Review 스케줄 확인
    ④ Event Trigger 조건 점검
    ⑤ 초과/발생 항목 → WorkItem(beo, ALERT) 생성
    ⑥ 모니터링 저널에 기록
```

비오님이 SESSION BOOT 시 → 직전 세션 이후 발생한 알림 요약이 자동 표시된다.

### 16.3 SESSION BOOT 마이크로 브리핑 (추가)

현재 SESSION BOOT에 Step 7을 추가한다.

```
Step 7. 시스템 건강 브리핑 (마이크로 리뷰)
    - GHS 현황: 0.82 (정상 / 경보 / 위험)
    - 직전 세션 이후 Event Trigger: 2건
    - 오버듀 Review: Weekly Failure Audit 2일 초과
    - 외부 신호: EU AI Act 시행령 세부 발표 감지
    - 자동 준비된 행동: [캐디가 WorkItem으로 사전 작성]
```

비오님은 새 세션을 열면 즉시 시스템 현황을 파악한다.

### 16.4 Conditional EAG (조건부 사전 승인)

매번 EAG를 받는 대신, 조건을 미리 승인한다.

예시:
```
EAG-S322-CONDITIONAL-MONITOR-001:
  조건: Calibration_Error > 20%
  승인 행동: 캐디가 Emergency Calibration Review를 즉시 착수한다
  한도: 1회 / 30일
  만료: 2026-12-31
```

비오님은 조건을 한 번 승인한다. 조건 충족 시 시스템이 자동 착수한다. 이것이 "시작 버튼 없는 실행"의 올바른 구현이다. 무한정 자율 실행이 아니라 비오님이 미리 승인한 조건과 한계 내에서만 작동한다.

**전역 회로 차단기 (Global Circuit Breaker):** 24시간 내 자동 실행되는 Conditional EAG의 총합은 비오님이 사전 설정한 전역 한도(N건)를 초과할 수 없다. 개별 EAG의 한도와 독립적으로 작동한다. 한도 초과 감지 시 즉시 Fail-Closed. 이 규칙은 Area 5(Sovereign Authority)에 하드코딩된다.

### 16.5 Time + Event Hybrid

```
사건 없어도 → Time-Driven 스케줄은 반드시 실행 (기준선)
사건 발생 시 → Event-Driven이 추가 실행 (가속)
두 경로가 겹쳐도 → 중복 처리 방지 (deduplication)
```

### 16.6 Phase 1 즉시 구현 가능 항목

복잡한 인프라 없이 즉시 시작할 수 있는 것들:

1. SESSION_CONTEXT에 `review_schedule` 필드 추가:
   ```json
   {
     "review_schedule": {
       "weekly_failure_audit": {"last_run": "2026-07-01", "next_due": "2026-07-08"},
       "monthly_assumption_review": {"last_run": "2026-06-01", "next_due": "2026-07-01"},
       "quarterly_constitution_review": {"last_run": null, "next_due": "2026-10-01"}
     }
   }
   ```

2. SESSION BOOT Step 7에서 오버듀 감지 + 경보 표시

3. Conditional EAG 1개 등록 (가장 중요한 임계값 1개부터)

4. aiba-monitor.service 설계 의뢰 (도미 DEP)

---

## 17. 구현 우선순위 (Always-On 관점)

레이더(레이더처럼 돌아가는 시스템)를 만들기 위한 순서:

```
Step 1: SESSION_CONTEXT review_schedule 필드 추가 + SESSION BOOT Step 7 (현재 세션 가능)
Step 2: 첫 Conditional EAG 등록 (최고 우선 임계값 1개)
Step 3: aiba-monitor.service 설계 DEP → 도미에게 의뢰
Step 4: aiba-monitor.service 구현 + systemd 등록
Step 5: GHS 자동 계산 구현 (Area 13 통합)
Step 6: Constitution Review Proposal 자동 생성 (Quarterly)
```

Step 1-2는 추가 인프라 없이 이번 또는 다음 세션에서 착수 가능하다.

---

## 18. Open Design Questions (Phase 2-3)

| 항목 | 제안자 | 이관 사유 |
|-----|-------|---------|
| Merkle Graph Anchor | 제니 | Phase 1 복잡도 과다 |
| Cryptographic Key Release | 제니 | Phase 2 |
| GHS 가중치 최적화 | 도미 | 운영 데이터 필요 |
| Multi-domain Signal Model | 캐디 | 도메인 파트너십 필요 |
| Full Confidence Calibration 자동화 | 도미·제니 | 데이터 누적 필요 |

---

## 19. 변경 이력

| 버전 | 주요 변경 |
|-----|---------|
| v0.1 | 최초 통합 |
| v0.2 | Graph/Ledger 구분, Wrong Cost Factor, Counter-Hypothesis, Retirement, Graceful Degradation, 기존 코드 매핑 |
| v0.3 | Non-Goals, 4계층, Decision Quality 5차원, VEV, Reversibility, Strategic Alignment 2D, Organizational Adaptation, Confidence Calibration, 신뢰도 분리, Coordinated Influence 방어, Pre-Mortem, I/O Boundary 3계층, Differential EAG, WorkItem, Operation Layer, Kanban=View, Conflict Resolution, Challenge/Appeal, Sovereign Veto |
| v1.0 | **5계층(SIM 추가), Always-On 원칙(Non-Goals #6), Goodhart's Law 방어(Non-Goals #7), 기억과 망각(Non-Goals #8), Section 15 Recursive Self-Improvement Protocol(AIF Area 7), Section 16 Always-On Runtime Architecture, GHS, Conditional EAG + 전역 회로 차단기, SESSION BOOT Step 7, Self-Improvement Debt, aiba-monitor.service, Time+Event Hybrid** |

---

*이 문서는 AIBA의 Living Constitution이다. 비오님 EAG 승인 후 govdoc_freeze_gate.py FROZEN_HASH에 등록된다. 이후 개정은 Section 14의 헌법 개정 프로토콜을 따른다.*

*다음 단계: (1) 비오님 EAG 승인 → v1.0 동결 등록. (2) Manifesto 추출 (2페이지). (3) aiba-monitor.service 설계 DEP를 도미에게 의뢰. (4) Area 1 설계 DEP.*


