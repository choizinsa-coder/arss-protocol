# AIBA Collective Intelligence Casebook

---

## Glossary

| 용어 | 설명 |
|---|---|
| **EAG** | Executive Approval Gate. 비오님(CEO)의 최종 승인 게이트. 모든 비가역적 변경에 필수. |
| **DEP** | Deployment. 도미(설계) → 제니(검증) → 비오(EAG) → 캐디(실행) 순으로 진행되는 변경 파이프라인. |
| **OI** | Observation Item. 운영 중 발견된 이상 징후 또는 개선 필요 항목. |
| **INC** | Incident. 거버넌스 위반 또는 시스템 이상이 발생한 사건. |
| **Freeze** | Goal 1 Freeze. 핵심 거버넌스 파일을 해시로 동결하여 무결성을 보호하는 장치. |
| **Tier D** | 오래된 기록을 archive 파일로 이관하는 메커니즘. SESSION_CONTEXT 경량화 목적. |
| **SSOT** | Single Source of Truth. SESSION_CONTEXT_S{n}_FINAL.json이 유일한 상태 기록. |
| **TRUST_READY** | 제니(CRO)가 변경안을 신뢰 가능하다고 판정한 상태. |
| **chain.tip** | 가장 최근 git commit hash. 상태 무결성의 기준점. |

---

## Case 01

### Governance Freeze Blind Spot: How a Missing Pre-Check Broke the Deployment Pipeline

---

### Case Metadata

| 항목 | 내용 |
|---|---|
| **Case ID** | CASE-001 |
| **Incident ID** | INC-S249-001 |
| **Session Range** | S249 |
| **Date** | 2026-06-15 |
| **Related DEP** | EAG-S249-TIERD-MIGRATE-001 / ORD-S249-GOV-002 |
| **Outcome** | 보완 DEP(215f4d8)로 완전 해소. 데이터 손실 0. |
| **7-Axis Classification** | 붕괴 축: **Execution** (사전 검증 절차 누락) / 치유 축: **Governance** (Freeze Registry 갱신) |

---

### 1. Executive Summary

AIBA는 SESSION_CONTEXT의 비대화 문제를 해결하기 위해 Tier D 이관 메커니즘을 구축하고 배포했다. 배포 직후 freeze guard 테스트 2건이 실패했다. 기능 자체의 결함이 아니었다. 문제는 배포 전 사전 점검 단계에서 변경 대상 파일(session_close_generator.py)이 Goal 1 Freeze 보호 대상임을 확인하지 않은 것이었다. 의존성 분석은 수행했으나 거버넌스 보호 대상 여부 확인은 누락되었다. AIBA는 즉시 원인을 실측으로 확인하고 보완 DEP(ORD-S249-GOV-002)를 수행하여 문제를 완전히 해소했다. 이 사건은 "의존성 검사와 거버넌스 보호 대상 검사는 별개의 절차"라는 핵심 교훈을 남겼고, 이후 freeze 사전점검이 배포 절차의 필수 단계로 명문화되었다.

---

### 2. Background

S249 시점에서 AIBA의 SESSION_CONTEXT는 수십 개의 세션 기록이 누적되어 크기가 지속적으로 증가하고 있었다. 이는 SESSION BOOT 시 로드 부담을 키우고 컨텍스트 창을 압박하는 구조적 문제였다. 이를 해결하기 위해 오래된 기록(s215~s239, 50건)을 별도 archive 파일로 이관하고 active SESSION_CONTEXT를 경량화하는 Tier D 이관 메커니즘을 구현하고 있었다. 해당 기능(session_close_generator.py)은 SESSION CLOSE 시 자동으로 실행되는 핵심 컴포넌트로, 거버넌스 자산과 밀접하게 연관되어 있었다.

**Evidence Sources**
- `SESSION_CONTEXT_S265_FINAL.json` -> `caddy_governance_record_s249`
- `EAG-S249-TIERD-MIGRATE-001` (commit 5d7cc14)

---

### 3. Trigger Event

Tier D 이관 메커니즘(session_close_generator.py) 배포(commit 5d7cc14) 직후 전체 pytest를 실행했다. `test_goal1_freeze.py` 내 freeze guard 테스트 2건이 FAIL을 반환했다. 직전까지 통과하던 테스트였으며, 신규 배포 이후 최초 실패였다. freeze guard는 핵심 거버넌스 파일의 무결성을 검증하는 최후의 안전장치다.

---

### 4. Investigation

**최초 가설:** session_close_generator.py의 Tier D 이관 로직 자체에 버그가 있을 것이다.

**조사 과정:**
1. 이관 로직 실행 결과 확인 -> 정상 동작. s215~s239 50건 archive 이관 성공.
2. freeze guard 실패 원인 추적 -> `test_goal1_freeze.py`가 참조하는 해시 기준선이 stale 상태임을 발견.
3. 기준선 해시 추적 -> `session_close_generator.py`가 Goal 1 Freeze 등록 파일임을 확인. 파일이 변경되었으나 freeze registry(test_goal1_freeze.py)의 해시 기준선이 갱신되지 않은 상태.

**폐기된 가설:** 이관 로직 버그. -> 이관 로직은 정상. 문제는 배포 전 사전 점검 단계였다.

**확인된 사실:** 사전 점검에서 의존성 grep(apply_delta/build_archive/test_session_close_generator)은 수행했으나, freeze registry(test_goal1_freeze.py) 점검을 누락했다.

**Evidence Sources**
- `caddy_governance_record_s249.incidents[INC-S249-001]`
- `caddy_governance_record_s249.oi_observations`
- commit 5d7cc14, commit 215f4d8

---

### 5. Root Cause

**Root Cause**
거버넌스 보호 대상(Goal 1 Freeze) 여부를 확인하는 사전 검증 절차가 변경 영향도 분석에 포함되지 않았다.

**Explanation**
배포 전 의존성 분석은 코드 레벨 의존성(apply_delta, build_archive, test_session_close_generator)만을 대상으로 했다. 그러나 session_close_generator.py는 동시에 Goal 1 Freeze 보호 파일 목록에 등재되어 있었다. 거버넌스 보호 장치(Freeze Registry)와 코드 의존성 분석은 별개의 검증 레이어였으나, 배포 절차에 이 구분이 명시되어 있지 않았다. 결과적으로 보호 대상 파일이 변경되었음에도 거버넌스 검증 없이 배포가 진행되었다.

**Evidence Sources**
- `caddy_governance_record_s249.caddy_self_report[0]`
- `EAG-S249-TIERD-MIGRATE-001` 사전 점검 기록

---

### 6. Resolution

**수행한 조치 (ORD-S249-GOV-002):**
1. freeze stale 근본원인 실측: 동결 해시(b304b503)는 S246 기준이었으나 실제 현재 해시(8b9a2ecf)는 S248 이후 정상 append 상태였음을 확인.
2. session_close_generator.py를 Goal 1 Freeze Registry에 정식 등록.
3. journal baseline(S248)을 정정하여 freeze stale 해소.
4. freeze guard 테스트 전체 재실행 -> PASS 확인.

**결과:** commit 215f4d8. pytest 1642 passed / 0 failed / 94 skipped. 데이터 손실 0.

**Evidence Sources**
- `ORD-S249-GOV-002` (commit 215f4d8)
- `caddy_governance_record_s249.oi_observations[1]`

---

### 7. Governance Analysis

**작동한 보호 장치:** pytest freeze guard가 배포 후 즉시 회귀를 탐지했다. 탐지 장치는 정상 작동했다.

**부족했던 보호 장치:** 배포 전 단계에서 Freeze Registry 확인을 강제하는 예방 절차가 없었다. 탐지(사후)는 있었으나 예방(사전)이 부재했다.

**의사결정 분석:** 배포 담당자(캐디)는 코드 의존성 분석을 수행했고 이는 정상 절차였다. 그러나 거버넌스 자산(Freeze Registry)이 별도의 검증 레이어라는 인식이 배포 절차에 내재화되어 있지 않았다. 이는 개인 실수가 아니라 절차 설계의 공백이었다.

**후속 조치:** 이 사건 이후 S251에서 govdoc_freeze_gate(boot/close 게이트)가 신설되어 Freeze 무결성 검증이 구조적으로 강제되었다. 예방 장치가 사후 추가된 사례다.

---

### 8. Collective Intelligence Contribution

**Domi (CSO 설계)**
보완 DEP(ORD-S249-GOV-002)의 수정 방향을 설계했다. freeze stale의 근본 원인이 S248 클로즈 시 baseline 갱신 누락임을 구조적으로 분석하고, Registry 갱신 + journal baseline 정정의 2단계 해결 경로를 제안했다.

**Jeni (CRO 검증)**
보완 DEP가 기존 거버넌스 구조와 충돌하지 않는지 검증했다. 수정이 freeze 체인의 단조성을 유지하는지, 사이드 이펙트가 없는지를 확인하고 TRUST_READY를 판정했다.

**Caddy (COO 실행)**
실제 테스트 실패를 최초 감지하고 원인 추적을 수행했다. 이관 로직 자체가 아닌 사전 점검 누락임을 실측으로 확인했으며, 보완 DEP 실행 후 pytest 전체 재검증으로 해소를 확인했다. 또한 이 사건을 INC-S249-001로 SSOT에 기록하여 경험 좌표를 보존했다.

---

### 9. Key Lessons

1. **의존성 검사는 거버넌스 보호 대상 검사를 대체하지 못한다.** 코드 레벨 의존성과 거버넌스 자산(Freeze Registry, 동결 파일 목록)은 별개의 검증 레이어다. 두 검사는 병렬로 수행되어야 한다.

2. **탐지 장치(pytest)는 예방 장치(사전 점검)를 대체하지 못한다.** 배포 후 테스트 실패는 문제를 발견하지만 이미 배포가 완료된 후다. 배포 전 Freeze Registry 확인이 절차에 포함되어야 한다.

3. **보호 규칙은 문서가 아니라 실행 가능한 검증 절차로 존재해야 한다.** Goal 1 Freeze 규칙이 존재했음에도 배포 절차에 해당 검증 단계가 없었기 때문에 누락이 발생했다. 규칙은 절차에 내재화되어야 한다.

---

### 10. Pattern Extracted

#### Freeze Protection Pattern

**Context**
거버넌스 보호 대상 파일(Goal 1 Freeze 등재 파일)을 변경하거나 해당 파일에 의존하는 컴포넌트를 배포할 때.

**Problem**
변경 영향도 분석이 코드 레벨 의존성에만 집중되어 거버넌스 보호 대상 여부를 확인하지 않으면, 배포 후 freeze guard 실패라는 형태로 회귀가 발생한다.

**Solution**
배포 전 체크리스트에 Freeze Registry 확인 단계를 필수 항목으로 포함한다. 이상적으로는 배포 게이트(boot/close freeze gate)가 이를 자동으로 강제한다.

**Trade-off**
사전 점검 단계가 늘어나 배포 절차가 다소 길어진다. 그러나 배포 후 freeze 실패 후 보완 DEP 수행의 비용이 훨씬 크다.

---

*작성: AIBA Caddy (S266) -- SESSION_CONTEXT_S265_FINAL.json 실측 기반*
*검증 체인: Domi [DESIGN] -> Jeni [TRUST_READY] -> Beo [EAG 확정]*
*템플릿 버전: S266 EAG 확정본 (도미 10섹션 + 제니 권고 2건 반영)*
