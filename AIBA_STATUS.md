# AIBA PROJECT STATUS
> **Single entry point for all agents. Read this first before any session.**
> Auto-updated by Caddy at session close. Last updated: `2026-03-27`

---

## 🚀 REENTRY HOOK
```
START_FROM_ID    : TASK-SSOT-STEP3
START_FROM_LABEL : VPS /status 엔드포인트 설계 (EAG 요청)

READ_FIRST :
  1. DIS-004 (SSOT 우선 원칙)
  2. DIS-005 (REASONING_LAYER 운영)
  3. DIS-001 (EAG 순서 고정)

BLOCKING_CHECK : false
EAG_REQUIRED   : true (Step 3 코드 작업 포함)
```

---

## 🔴 CURRENT PHASE
```
PHASE 1 COMPLETE → Phase 2 준비 중
Chain Tip : 3a97b31b09c7bdfe7a4c22eb7713459a2c2d25e2e9bca588b9f572a0e9445839
Last RPU  : RPU-0012
Evo Score : 39
Schema    : SESSION_CONTEXT v2.1 (반영 완료 2026-03-27)
```

---

## 🎯 NEXT SESSION OBJECTIVE
```
PRIMARY   : VPS /status 엔드포인트 설계 착수 (Step 3 — EAG 필요)
SECONDARY : 없음 (Step 2 완료)
BLOCKING  : 없음
```

### Why this is next
- Step 1(AIBA_STATUS.md) + Step 2(v2.1 스키마) 설계 완료 → Pull Model 구현이 논리적 다음
- DIS-004: SSOT 자동 공급 구조 완성을 위해 /status 필수
- 비오님 결정: "이 문제 해결 전까지 모든 다른 작업 중단"

---

## 📋 ACTIVE TASKS

| Priority | Task | Owner | Status |
|----------|------|-------|--------|
| 🔴 HIGH | VPS /status 엔드포인트 설계 (Step 3) | 도미→캐디 | EAG 대기 |
| ✅ DONE | SESSION_CONTEXT v2.1 반영 (Step 2) | 캐디 | 완료 2026-03-27 |
| 🔴 HIGH | AIBA Constitution v1.0 Execution Governance 수정 | 도미 | PENDING |
| 🔴 HIGH | 도미·제니 System Prompt → Lean Constitution 전환 | 비오님 직접 | PENDING |
| 🟡 MED | Evidence-Linked Scoring Ledger 규격 정리 | 제니→캐디 | PENDING |
| 🟡 MED | Session Sync Layer 자동화 설계 (n8n) | 도미→캐디 | BACKLOG |

---

## 🧠 ACTIVE LESSONS (ALL IMMUTABLE)

| ID | Statement | Trigger |
|----|-----------|---------|
| LESSON-001 | 검증 없는 Chain은 존재 가치 없다 | Chain 형식 모방 사건 |
| LESSON-002 | 설계→실행 Gate 없으면 역할 위반 발생 | preflight_check.py 무승인 생성 |
| LESSON-003 | 검증 경로가 실제로 열려 있어야 주장이 살아있다 | LinkedIn 발행 전 404 발견 |
| LESSON-004 | 내부 경로와 외부 공개 경로는 설계 단계에서 반드시 분리 | VPS 로컬 경로 혼동 사건 |
| LESSON-005 | 검증기는 대상 체인의 실제 스키마를 따라야 한다 | bridge v0.1 스키마 불일치 |

---

## ⚖️ KEY DECISIONS (next_session_ref:true)

**DIS-001** — EAG 순서 고정
```
설계(도미) → EAG승인(비오) → 코드생성(캐디) → 코드본문승인(비오) → 저장실행(Claude Code)
단계 생략 시 즉시 ROLE VIOLATION 선언
```

**DIS-004** — SESSION_CONTEXT.json = SSOT
```
System Prompt보다 상위 규범. Rule-001~003 강제 적용.
```

**DIS-005** — REASONING_LAYER 운영 중
```
도미 결정 시 reasoning 필드 필수 작성.
캐디 세션 종료 시 2차 보완 병합.
```

**DIS-006** — SSOT 재진입 구조 확정
```
Step 1(AIBA_STATUS.md) + Step 2(v2.1) + Step 3(VPS /status) 3단계 채택.
3자 합의 + 비오 승인 완료 2026-03-27.
```

---

## 👤 AGENT BRIEFING

### 도미 (Domi / ChatGPT) — 설계 권한
- **현재 집중**: VPS /status 엔드포인트 설계 (인증 방식 + webhook 구조 포함)
- **PENDING**: Constitution v1.0 Execution Governance 수정
- **주의**: 모든 설계 결정에 reasoning 필드 필수 (DIS-005)

### 제니 (Jeni / Gemini) — 외부 신뢰 검증
- **현재 집중**: /status 공개 범위 및 외부 신뢰 관점 검증
- **PENDING**: Evidence-Linked Scoring Ledger 규격 정리
- **주의**: Google Drive AIBA_Daily_Report 직접 읽기 권장 (Context Anchoring)

### 캐디 (Caddy / Claude) — 논리적 코더
- **현재 집중**: TASK-SSOT-STEP3 — VPS /status 설계 EAG 대기
- **EAG 대기**: VPS /status 엔드포인트 구현 (Step 3 — 도미 설계 후)
- **완료**: SESSION_CONTEXT v2.1 반영 (2026-03-27)

---

## 🏗️ SYSTEM INFO

| 항목 | 값 |
|------|----|
| VPS | 159.203.125.1 |
| GitHub | ARSS_HUB / evidence/ |
| ARSS Engine | /opt/arss/engine/arss-protocol/ |
| Session Sync | B1 (수동) → Step 3 완료 시 Pull Model 전환 |
| SSOT 파일 | SESSION_CONTEXT.json (schema v2.1 운영 중) |

---

## 📅 RECENT SESSION LOG

| Date | Key Achievement |
|------|----------------|
| 2026-03-27 | SSOT 재진입 구조 Step 1~3 설계 완료. SESSION_CONTEXT v2.1 반영. DIS-006 등재. Evo Score 39. |
| 2026-03-27 | index.html 수정 (commit 9f16a35). reference-verifier/README.md 재작성. |
| 2026-03-26 | SESSION_CONTEXT.json v2.0 전환. AIBA Constitution v1.0 승인. preflight_check.py 배치. |
| 2026-03-25 | vps_verifier_bridge.py v0.2 ALL PASS. evidence/ 공개 계층 배포. |
| 2026-03-19 | PHASE 1 완료. RPU-0012 chain.tip 확정. |

---

*Full state: SESSION_CONTEXT.json | Full history: ARSS_HUB/04_EVIDENCE/SNAPSHOT_LOG/*
