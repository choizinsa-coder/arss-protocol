# BRIEFING-DOMI-S150-PHASE-A
## Context Gateway 설계 의뢰

**수신**: 도미 (System Designer / Architecture Authority)  
**발신**: 캐디  
**세션**: S151  
**태스크**: PT-S150-CONTEXT-GATEWAY-ORCHESTRATION  
**EAG 단계**: EAG-1 설계 승인 대상  
**상태**: 설계 의뢰 중

---

## 1. 배경 및 목적

### 핵심 목표

> **"세 에이전트가 동일한 최신 현실을 보게 만드는 것"**

S150 3자 토론(도미·제니·캐디) 합의 결과, 자동화 완성보다 **Context Gateway 먼저 확립**으로 방향이 정해졌다.

- Observation Authority ≠ Mutation Authority ≠ Execution Authority 원칙 유지
- Watchdog(Phase B), Write Plane 2-tier(Phase C)는 Phase A EAG 완료 후 착수

### 합의 경위 (S150)

1. "자동화 완성"을 서두르지 않고 Context Gateway를 먼저 잠그기로 결정
2. Step 1(SESSION_CONTEXT VPS 배포)을 경량 PEC 후 실행 — **S151 착수 전 비오님이 이미 완료**
3. Watchdog / Write Plane을 분리해 복잡도 폭증 방지
4. **glob 기반 Projection 최신성 탐색의 구조적 취약점 발견 → Freshness Authority 필요성 확정**

---

## 2. 현재 상태 (S151 기준)

### 가동 중인 인프라

| 서비스 | 포트 | 상태 |
|---|---|---|
| aiba-mcp-bridge | 8443 | ✅ active |
| aiba-mcp-write | 8444 | ✅ active (write_file 403 — 승인 구조 미해소) |
| aiba-observation | 8446 | ✅ active |
| aiba-n8n | - | ✅ active |
| aiba-status | - | ✅ active |

### 핵심 갭

| 갭 | 내용 |
|---|---|
| **Freshness Authority 없음** | glob + mtime 탐색 — canonical 최신 파일 결정 규칙 미존재 |
| **Shard write-back 없음** | context/ shard 파일 자동 갱신 메커니즘 미설계 |
| **역할별 Projection 미분화** | ALLOWED_TOP_KEYS 14개 — 도미/제니 역할별 분화 미설계 |
| **Stale Projection 차단 규칙 없음** | stale 시 에이전트 동작 규칙 미정의 |

---

## 3. 설계 요청 범위 (Phase A 한정)

Phase A는 다음 5개 항목의 **설계 결정**을 요청한다.  
구현 명세(IMPLEMENTABLE)는 도미 설계 확정 후 캐디가 작성한다.

---

### A-1. Projection Freshness Authority ← **최우선**

> "누가 최신 SESSION_CONTEXT를 결정하는가"

**현재 문제**: `glob("SESSION_CONTEXT_S*_FINAL.json")` + mtime 탐색  
→ 파일 혼재 시 오인 위험 (`S150_FINAL_fix.json`이 canonical로 오인될 수 있음)

**캐디 제안 (판단 참고용)**:

```json
// SESSION_CONTEXT_POINTER.json (VPS 루트에 위치)
{
  "canonical": "SESSION_CONTEXT_S151_FINAL.json",
  "session": 151,
  "updated_at": "2026-05-24T00:00:00+09:00",
  "authority": "caddy"
}
```
- projection_builder가 POINTER 파일을 먼저 읽고 canonical 결정
- POINTER 파일 없으면 glob fallback (기존 동작 유지)

**도미 판단 요청 — 4개 방식 중 선택 또는 대안 제시**:

| 방식 | 설명 |
|---|---|
| manifest 기반 latest pointer | 별도 manifest 파일로 canonical 추적 |
| **active_session pointer** | 캐디 권장 — 단순, 명확, 최소 의존성 |
| canonical_current.json alias | symlink 또는 copy alias 방식 |
| monotonic session index validation | session number 단조 증가 검증 |

---

### A-2. SESSION_CONTEXT 최신성 기준

- 세션 종료 시 VPS 배포 의무화 조건 정의
- **캐디 session_close_rules 개정 대상 항목** 명세 (도미 결정 → 캐디 반영)
- "배포 완료"의 정의: git commit 포함 여부, n8n WF-01 감지 확인 포함 여부

---

### A-3. Shard write-back 원칙

- 어떤 shard가, 언제, 어떤 트리거로 갱신되는가
- 세션 종료 자동 갱신 대상 shard 선정 기준
- **캐디 write_file 403 미해소 구간 임시 운영 방안** (SCP 수동 유지 조건)

대상 shard 후보:

| Shard | 경로 | 갱신 주기 |
|---|---|---|
| active tasks | context/tasks/active.json | 매 세션 |
| lessons | context/lessons/lessons.json | 신규 lesson 발생 시 |
| visibility history | context/metrics/visibility_history.json | 매 세션 |
| vps state | context/vps/state.json | VPS 변경 시 |

---

### A-4. 역할별 Projection 범위 (role-scoped)

- **도미용 Projection**: 설계 판단에 필요한 필드
- **제니용 Projection**: 거버넌스·보안 감사에 필요한 필드
- 현재 `ALLOWED_TOP_KEYS` 14개 → 역할별 분화 기준 결정
- projection_builder 파라미터 확장 방식 (`role` 파라미터 추가 여부)

---

### A-5. Stale Projection 차단 규칙

- Freshness Authority 기반 stale 판정 기준 (session 차이 허용 범위)
- stale 시 도미·제니 동작 규칙:
  - PENDING 선언 후 대기
  - 경고 후 계속 (degraded mode)
  - 작업 거부
- stale 선언 주체 및 에스컬레이션 경로

---

## 4. 제약 조건

| 제약 | 내용 |
|---|---|
| **Phase B/C 설계 포함 금지** | Watchdog / Write Plane 2-tier는 Phase A EAG 완료 후 착수 |
| **구현 명세 생략 가능** | 설계 결정(방향, 원칙, 구조)만 요청. 코드 레벨은 캐디 담당 |
| **단순성 우선** | Context Gateway 자체가 새 복잡도 원천이 되어서는 안 됨 |
| **SSOT 원칙 유지** | SESSION_CONTEXT.json이 여전히 SSOT 권위를 가짐 |

---

## 5. 산출물 요청

도미가 제공할 산출물:

1. **A-1 ~ A-5 각 항목에 대한 설계 결정** (방향, 원칙, 구조)
2. **캐디 IMPLEMENTABLE 착수를 위한 기준선** (구현 가능한 수준의 명세)
3. **제니 TRUST_READY 체크리스트 제안** (선택 — 도미 판단)

---

## 6. 후속 절차

```
도미 설계 완료
  → 캐디 IMPLEMENTABLE 초안 작성
  → 제니 TRUST_READY 검증
  → 비오님 EAG-1 승인
  → 캐디 구현 실행
```

---

*발행: 캐디 / S151 / 2026-05-24*  
*기준 파일: tools/sandbox/caddy/active/notes/task-S150-001-caddy-final_draft.md*  
*태스크: PT-S150-CONTEXT-GATEWAY-ORCHESTRATION*
