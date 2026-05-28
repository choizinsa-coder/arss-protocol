# AIBA Sandbox Collaboration & Orchestration Architecture — FINAL

생성일: 2026-05-23
세션: S144
상태: FINAL DIRECTION / PRE-EAG
생성자: Domi (설계) / Caddy (검토 반영) / 비오님 (승인)

---

## 1. 목적

본 문서는 S144에서 확인된 sandbox 기반 multi-agent collaboration 구조 문제와
향후 orchestration 방향성을 통합 정리한 최종안이다.

---

## 2. S144에서 확인된 핵심 현실

### 2.1 기존 협업 구조의 실체

기존 "세 에이전트 협업"의 실제 구조:

```
Caddy
→ Domi 역할 reasoning 생성  ← 캐디가 도미를 "연기"
→ Jeni 역할 reasoning 생성  ← 캐디가 제니를 "연기"
→ 다시 Caddy reasoning 수행
→ recursive expansion
→ context saturation
→ session instability
```

결론: collaboration simulation (협업 시뮬레이션) 이 발생하고 있었음.
실체: "협업처럼 보이는 독백"

### 2.2 Sandbox 실측 결과

sandbox 구조 (/tools/sandbox/domi/, /jeni/, /caddy/, /common/)는
VPS에 실제 존재하나, 실제 artifact 기록은 0건.

결론: sandbox는 workbench가 아니라 빈 디렉토리였음.

---

## 3. 핵심 철학 전환

| 기존 | 새 방향 |
|---|---|
| Conversation-first | Artifact-first |
| Role-play | Contract exchange |
| Reasoning 공유 | 결과 파일 전달 |
| 대화창 협업 | Sandbox 파일 교환 |

핵심 원칙:
> artifact는 기록이 아니라 협업 계약의 물리적 실체다.
> 대화창 reasoning은 operational artifact가 아니다.

---

## 4. Sandbox 재정의

Sandbox는 이것이 아님:
- memory dump
- reasoning 저장소
- 잡담 공간

Sandbox 새 정의:
> Shared Collaboration Workbench (공유 협업 작업대)

역할:
- agent artifact exchange layer
- dispatch coordination layer
- operational state surface

---

## 5. Agent 역할 재정립

### DOMI
허용: architecture, governance, topology, contract, risk analysis
금지: implementation, deployment, runtime confirmation

### JENI
허용: audit, PASS/FAIL, trust validation, fail-closed review
금지: execution, orchestration, deployment

### CADDY
허용: implementation, operational execution, measurement
주의: 현재 orchestration burden 과다 — 분산 필요

---

## 6. Session-Separated Collaboration 구조

```
Step 1 (Caddy Session)
  → 실측 수행
  → caddy/active/notes/ 에 observation 기록
  → 세션 종료

Step 2 (Domi Session)
  → caddy observation 읽기
  → 설계 생성
  → domi/active/proposals/ 에 기록
  → 세션 종료

Step 3 (Jeni Session)
  → domi proposal + caddy receipt 읽기
  → 검증 수행
  → jeni/active/audit/ 에 기록
  → 세션 종료

Step 4 (Caddy Session)
  → jeni PASS 확인
  → 구현 실행
  → caddy/active/receipts/ 에 기록
```

핵심 효과: context reset / recursive collaboration 제거 / traceability 증가

---

## 7. Trigger Gap 구조 (현실)

현재 4개의 Gap을 비오님이 수동으로 채우고 있음:

```
Gap-1: Caddy observation 완료 → 누가 Domi를 깨우는가?
Gap-2: Domi proposal 저장 → 누가 Jeni를 깨우는가?
Gap-3: Jeni PASS → 누가 Caddy 구현을 허가하는가?
Gap-4: Caddy 구현 완료 → 누가 다음 상태를 결정하는가?
```

Phase 1 목표: 비오 제거가 아니라 orchestration burden 구조화.

---

## 8. 단계적 구조

### Phase 0 — Artifact Discipline (즉시)
- sandbox artifact 사용 습관화
- role simulation 제거
- ticket 기반 상태 관리 시작

### Phase 1 — Human-Gated Dispatch
```
sandbox 변화 감지 → watchdog → dispatch pending
→ Beo 승인 → 다음 agent 호출
```
자동 dispatch 금지.

### Phase 2 — Semi-Automated Dispatch
낮은 위험 작업만 자동 연결.

### Phase 3 — Limited Autonomous Orchestration
엄격히 제한된 자율 루프 (TTL, max dispatch, fail-closed 필수).

---

## 9. Watchdog 정의

Watchdog는:
- reasoning 수행 안 함
- 판단자 아님
- intelligent orchestrator 아님

역할 (signal router만):
- filesystem observation (polling)
- ticket transition detection
- stale detection
- timeout detection
- dispatch pending signaling

구현: systemd service (aiba-sandbox-watchdog), rule-based, non-LLM.

---

## 10. Governance Lock 구조

### LOCK-1: Task Ticket Integrity Lock
모든 ticket/state transition → hash sealing 필수

### LOCK-2: Agent I/O Transparency Lock
dispatch input / output / receipt → hash 형태 보존

### LOCK-3: Fail-Closed Circuit Breaker
TTL / max dispatch / max transition / timeout 초과 시
→ dispatch 중단 + sandbox lock + Beo approval required

### LOCK-4: Stale Observation Lock
- observation 2시간 초과: stale_warning
- observation 4시간 초과: stale_lock (재측정 요구)

### LOCK-5: Single Active Ticket Lock
동일 시점 active ticket은 반드시 1개만 허용.

---

## 11. Topology 방향

금지: mesh collaboration (에이전트 간 직접 대화)

권장: hub-and-spoke
```
Sandbox/Ticket Hub
← 모든 agent는 hub만 읽고 씀
← direct agent conversation 금지
```

---

## 12. 신규 Agent 방향

### ORION (Orchestrator Agent) — Phase 2+
역할: dispatch routing, queue management, stale cleanup
주의: 초기는 반드시 deterministic rule router로 제한 (reasoning 금지)

### LUMA (Cross-check Agent) — Phase 3
역할: contradiction/inconsistency detection
주의: Jeni 역할 정리 후 도입 검토

---

## 13. 즉시 우선순위 (Phase 0)

1. Session Boot Contract 확정
2. Ticket Schema 확정
3. Artifact Lifecycle (TTL 기준) 확정
4. sandbox에 실제 artifact 기록 시작
5. common/current_task_ticket.json 생성

---

## 14. 미해결 과제 (다음 설계 단계)

- orchestrator authority chain
- wake-up authority
- replay protection
- artifact retention policy
- cross-agent deadlock prevention
- token budget arbitration

---

## 15. 최종 결론

현재 최우선:
```
artifact discipline
bounded orchestration
dispatch governance
fail-closed collaboration
stateful sandbox operation
```

AIBA는 이제:
> Stateful Multi-Agent Collaboration Infrastructure
방향으로 진입하고 있다.

Boundary first. Orchestration second. Intelligence third.
