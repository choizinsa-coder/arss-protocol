# AIBA Collective Intelligence Casebook

---

## Glossary (Case 02 추가 용어)

> Case 01과 공유하는 기본 용어(EAG, DEP, OI, INC, Freeze, Tier D, SSOT, TRUST_READY, chain.tip)에 더해, Case 02에서 사용하는 고유 용어를 추가한다.

| 용어 | 설명 |
|---|---|
| **SESSION BOOT** | 매 세션 시작 시 POINTER → SSOT 로드 → 3-way 정합성 검사를 수행하는 의무 절차. |
| **Step 2-B** | SESSION BOOT 내 boot_gate 결과를 `read_file`로 소비하는 단계. |
| **purpose 파라미터** | `read_file` 호출 시 읽기 목적을 지정하는 인자. 화이트리스트 값(`OBSERVATION`)만 허용되며, 그 외 서술형 문자열은 DENY 처리된다. |
| **UNKNOWN_PURPOSE DENY** | purpose 값이 화이트리스트에 없을 때 반환되는 거부 응답. |
| **Role Drift Scoreboard** | 세션별로 각 에이전트(도미/제니/캐디)의 역할 이탈·오류 횟수를 집계하는 기록. |
| **PROMPT-FIX** | 운영 프롬프트(CADDY v3.7) 자체를 수정하여 반복 오류를 구조적으로 차단하는 조치. |

---

## Case 02

### The Recurring Slip: How a Free-Form Parameter Defeated Discipline Until Structure Replaced It

---

### Case Metadata

| 항목 | 내용 |
|---|---|
| **Case ID** | CASE-002 |
| **Incident ID** | INC-S258-001 / INC-S259-001 / INC-S260-001 (S257 포함 4회 연속 계열) |
| **Session Range** | S257 ~ S260 (재발) → S261 이후 (해소 실증) |
| **Date** | 2026-06-17 ~ 2026-06-18 |
| **Related DEP** | EAG-S260-PURPOSE-FIX-001 |
| **Outcome** | 프롬프트 구조적 고정으로 근본 차단. S261 이후 재발 0회 실증. |
| **7-Axis Classification** | 붕괴 축: **Execution** (표준값 미사용 절차 오용의 반복) / 치유 축: **Governance** (운영 프롬프트 구조 고정) |

---

### 1. Executive Summary

AIBA의 SESSION BOOT Step 2-B는 boot_gate 결과 파일을 `read_file`로 읽는다. 이 호출의 `purpose` 파라미터는 화이트리스트 값(`OBSERVATION`)만 허용한다. S257부터 S260까지 네 세션에 걸쳐, 캐디는 매번 `purpose`에 서술형 문자열을 넣었고 그때마다 `UNKNOWN_PURPOSE DENY`를 받은 뒤 `OBSERVATION`으로 정정했다. 운영 영향은 매번 즉시 정정으로 흡수되어 실질 손실은 없었으나, 같은 실수가 4회 연속 재발했다. 이는 개인의 주의력 문제가 아니라, 표준값이 운영 프롬프트에 명시되어 있지 않아 호출자가 매번 값을 임의 생성하도록 방치한 구조의 문제였다. S260에서 EAG-S260-PURPOSE-FIX-001을 통해 CADDY v3.7 프롬프트에 `purpose='OBSERVATION'`을 못박았고, S261 이후 재발이 0회로 떨어지며 효과가 실증되었다. 이 사건은 "반복되는 인적 오류는 더 강한 주의가 아니라 구조 변경으로 끊는다"는 교훈을 남겼다.

---

### 2. Background

SESSION BOOT은 매 세션 시작 시 수행되는 의무 절차로, 그 안의 Step 2-B는 boot_gate가 기록한 결과 파일을 `read_file`로 소비하여 거버넌스 동결 무결성을 확인하는 단계다. `read_file`의 `purpose` 파라미터는 읽기 목적을 지정하는 인자이며, 시스템은 화이트리스트에 등록된 값(`OBSERVATION`)만 허용하고 그 외의 서술형 문자열은 거부한다. 표준값 자체는 메모리와 운영 지식에 존재했으나, 정작 매 세션 반드시 실행되는 SESSION BOOT 프롬프트 본문에는 어떤 값을 써야 하는지가 고정되어 있지 않았다.

**Evidence Sources**
- `SESSION_CONTEXT_S266_FINAL.json` → `caddy_governance_record_s258/s259/s260`
- CADDY v3.7 SESSION BOOT Step 2-B 정의

---

### 3. Trigger Event

S257 세션 부팅 시 Step 2-B의 `read_file` 호출에서 `purpose`에 서술형 값이 사용되어 `UNKNOWN_PURPOSE DENY`가 반환되었다. 캐디는 즉시 `OBSERVATION`으로 정정하여 부팅을 이어갔다. 그러나 같은 오류가 S258, S259, S260에서 연속으로 반복되었다. S259에서는 한 세션 안에서 두 개의 서로 다른 서술형 값(`'SESSION BOOT 2-B gate verification'`, `'boot_gate_verification'`)을 연달아 시도한 뒤에야 표준값으로 정정하기도 했다. 매 세션 정정은 빨랐지만, 트리거 자체가 사라지지 않았다.

---

### 4. Investigation

**최초 가설:** 캐디의 일시적 부주의. 다음 세션에 주의하면 재발하지 않을 것이다.

**조사 과정:**
1. S257~S260 Role Drift Scoreboard 집계 → 캐디 오류 유형 중 purpose 오용이 반복 항목으로 분류됨(S249~S259 누적 집계에서 purpose 오용 3건이 별도 유형으로 잡힘).
2. "다음 세션 주의" 방식의 한계 확인 → S258, S259, S260에서 동일 오류가 계속 발생. 주의 환기는 재발을 막지 못했다.
3. 호출 지점 점검 → 표준값 `OBSERVATION`은 운영 지식에 있으나, 매 세션 실행되는 SESSION BOOT Step 2-B 프롬프트 본문에 값이 고정되어 있지 않음을 확인. 호출자가 매번 목적 문자열을 자유 서술하도록 방치된 구조.

**폐기된 가설:** 개인 주의력 문제. → 4회 연속 재발은 주의력으로 설명되지 않으며, 구조적 공백이 진짜 원인이었다.

**확인된 사실:** 프롬프트가 표준값을 강제하지 않아, 호출 시점마다 값이 새로 생성되고 그중 다수가 화이트리스트를 벗어났다.

**Evidence Sources**
- `caddy_governance_record_s258.incidents[INC-S258-001]`
- `caddy_governance_record_s259.incidents[INC-S259-001]`
- `caddy_governance_record_s260.incidents[INC-S260-001]`
- `caddy_governance_record_s260.oi_observations` (Role Drift Scoreboard S249~S259 집계: 캐디 8건, 유형 purpose오용 3)

---

### 5. Root Cause

**Root Cause**
매 세션 반드시 실행되는 운영 절차(SESSION BOOT Step 2-B)가 필수 파라미터의 표준값을 본문에 고정하지 않고, 호출자가 매번 값을 자유 서술하도록 열어 둔 구조적 공백.

**Explanation**
표준값(`OBSERVATION`)에 대한 지식은 존재했다. 그러나 지식이 존재한다는 것과 절차가 그 값을 강제한다는 것은 다른 문제다. SESSION BOOT 프롬프트는 "boot_gate 결과를 read_file로 소비하라"고 지시하면서도 purpose에 정확히 무엇을 넣어야 하는지를 못박지 않았다. 그 결과 호출자는 매 세션 목적을 의미 단위로 서술했고(예: 'gate verification'), 이는 화이트리스트 검증을 통과하지 못했다. 오류가 즉시 정정 가능했다는 점이 오히려 구조 결함의 노출을 지연시켰다 — 매번 빠르게 회복되었기에 "주의하면 된다"는 가설이 네 세션 동안 유지되었다.

**Evidence Sources**
- `caddy_governance_record_s259.caddy_self_report[0]` ("구조적 대책 필요")
- `caddy_governance_record_s260.oi_observations` (EAG-S260-PURPOSE-FIX-001 명시)

---

### 6. Resolution

**수행한 조치 (EAG-S260-PURPOSE-FIX-001):**
1. 원인을 개인 주의력이 아닌 프롬프트 구조 공백으로 재정의.
2. CADDY v3.7 SESSION BOOT Step 2-B 본문에 `purpose: "OBSERVATION"`을 명시적으로 고정(예시가 아니라 지정값으로 못박음).
3. 다음 세션부터 동일 절차에서 표준값이 그대로 사용되는지 관찰.

**결과:** S261 SESSION BOOT에서 purpose 파라미터가 `OBSERVATION`으로 정상 사용됨이 확인되었고(`caddy_governance_record_s261.caddy_self_report`: "EAG-S260-PURPOSE-FIX-001 구조적 차단 효과 확인"), 이후 S261~S266 동안 동일 오류 재발이 0회로 유지되었다.

**Evidence Sources**
- `caddy_governance_record_s260.eag_gates_this_session` (EAG-S260-PURPOSE-FIX-001)
- `caddy_governance_record_s261.caddy_self_report[0]`

---

### 7. Governance Analysis

**작동한 보호 장치:** 화이트리스트 검증(`UNKNOWN_PURPOSE DENY`)이 매번 잘못된 값을 즉시 차단했다. 시스템은 잘못된 읽기를 한 번도 통과시키지 않았다 — 안전 자체는 보장되었다.

**부족했던 보호 장치:** 잘못된 값의 *생성*을 막는 예방 장치가 없었다. 화이트리스트는 사후 거부(detection)였고, 호출자가 애초에 올바른 값을 쓰도록 강제하는 사전 고정(prevention)이 절차에 없었다.

**의사결정 분석:** S257~S259 동안의 대응은 "정정 후 다음 세션 주의"였고, 이는 사건을 INC로 기록하면서도 같은 층위의 해법(주의)에 머물렀다. 4회째인 S260에서 비로소 해법의 층위를 바꿔(주의 → 구조) 근본 차단에 도달했다. 반복 횟수 자체가 "층위 전환이 필요하다"는 신호였다.

**후속 조치:** 이 사건은 Manifesto v0.2에 반복 INC 에스컬레이션 규칙이 신설되는 배경이 되었다(`system_changes_s265`). 같은 오류가 일정 횟수 반복되면 개별 정정이 아니라 구조 변경으로 승급하는 규칙이다.

---

### 8. Collective Intelligence Contribution

**Domi (CSO 설계)**
원인을 "반복적 인적 오류가 아닌 설계적 결함"으로 재정의하고, 파라미터 고정화를 통한 구조적 차단(Structural Parameter Stability)을 해결 패턴으로 제시했다. 유연성 저하라는 트레이드오프도 함께 명시했다.

**Jeni (CRO 검증)**
Case 02 설계안에 대해 Root Cause와 치유 과정의 연결성을 더 구체화할 것을 권고했다(TRUST-ADVISORY). 이 권고는 5. Root Cause의 "지식 존재 ≠ 절차 강제" 구분을 명시적으로 기술하는 방향으로 반영되었다.

**Caddy (COO 실행)**
4회 연속 재발을 직접 겪고 기록한 당사자로서, S259 자기보고에서 "구조적 대책 필요"를 먼저 제기했다. S260에서 프롬프트 고정 조치를 실행하고, S261에서 효과를 실측으로 확인했으며, 본 사건을 INC 계열로 SSOT에 보존하여 경험 좌표를 남겼다.

---

### 9. Key Lessons

1. **같은 오류의 N회 반복은 주의력 문제가 아니라 구조 신호다.** 한 번의 실수는 부주의일 수 있으나, 4회 연속 동일 오류는 절차가 그 오류를 허용하고 있다는 증거다. 반복 횟수 자체를 "해법의 층위를 바꾸라"는 트리거로 읽어야 한다.

2. **사후 거부(detection)는 사전 고정(prevention)을 대체하지 못한다.** 화이트리스트가 잘못된 값을 매번 막아 주었기에 안전은 지켜졌지만, 잘못된 값의 생성 자체를 막지는 못했다. 필수 파라미터의 표준값은 호출 절차 본문에 못박혀야 한다.

3. **즉시 정정 가능한 오류일수록 구조 결함을 오래 가린다.** 회복이 빠르면 "주의하면 된다"는 가설이 유지되어 근본 원인 탐색이 지연된다. 손실이 작은 반복 오류일수록 의도적으로 구조 점검으로 승급시켜야 한다.

---

### 10. Pattern Extracted

#### Structural Parameter Stability Pattern

**Context**
매 세션 또는 매 호출 반복 실행되는 운영 절차가, 화이트리스트로 제한된 필수 파라미터(예: `purpose`)를 요구할 때.

**Problem**
절차 본문이 그 파라미터의 표준값을 고정하지 않고 호출자가 매번 값을 자유 생성하도록 두면, 생성된 값 중 일부가 화이트리스트를 벗어나 반복적인 거부와 정정이 발생한다. 개별 정정이 빨라 손실은 작지만 오류가 끊이지 않는다.

**Solution**
운영 절차(프롬프트/스크립트) 본문에 필수 파라미터의 표준값을 예시가 아닌 지정값으로 못박는다. 호출자의 자유 서술 여지를 제거하여, 값 생성 단계에서부터 올바른 값만 나오도록 강제한다.

**Trade-off**
파라미터 고정은 해당 절차의 유연성을 낮춘다(목적별로 다른 값을 쓰고 싶을 때 즉시 바꾸기 어렵다). 그러나 반복 실행 절차에서 자유도는 오류원이 되기 쉬우므로, 고정의 안정성 이득이 유연성 손실을 상회한다.

---

*작성: AIBA Caddy (S267) — SESSION_CONTEXT_S266_FINAL.json 실측 기반*
*검증 체인: Domi [DESIGN] → Jeni [TRUST-ADVISORY] → Beo [EAG 확정 대기]*
*템플릿 버전: S266 EAG 확정본 (도미 10섹션 + 제니 권고 2건 반영)*
