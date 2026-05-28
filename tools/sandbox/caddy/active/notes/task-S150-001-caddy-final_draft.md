# AIBA Context Gateway & Sandbox Orchestration — 3자 합의 최종안

**파일 ID**: task-S150-001-caddy-final_draft  
**작성**: caddy  
**세션**: S150  
**상태**: DRAFT  
**합의 주체**: 도미 (설계) + 제니 (검증) + 캐디 (실행)  
**비오 확인**: 완료 (S150)  
**목적**: S151 이후 작업 기준선

---

## 핵심 목표

> **"세 에이전트가 동일한 최신 현실을 보게 만드는 것"**

자동화는 이 목표 달성 이후의 문제.  
Observation Authority ≠ Mutation Authority ≠ Execution Authority 원칙 유지.

---

## 합의 도출 경위

### 비오 단기 목표 (S150 확정)

- **단기 목표 1**: 세 에이전트 sandbox 협업 자동화 완성
- **단기 목표 2**: SESSION_CONTEXT 비대화 해결 / 분산 자동 저장 / 세 에이전트 상시 접근 구조화

### 3자 토론 핵심 진전

1. "자동화 완성"을 서두르지 않고 Context Gateway를 먼저 잠그기로 한 점
2. Step 1을 "무위험 즉시 실행"이 아니라 "경량 PEC 후 실행"으로 수정한 점
3. Watchdog / Write Plane을 분리해 복잡도 폭증을 막은 점
4. glob 기반 Projection 최신성 탐색의 구조적 취약점 발견 → Freshness Authority 필요성 확정

---

## 현재 상태 (S150 기준)

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
| VPS SESSION_CONTEXT 없음 | projection_builder가 읽을 `SESSION_CONTEXT_S*_FINAL.json` VPS 미존재 → Projection STALE |
| Shard write-back 없음 | context/ shard 파일 자동 갱신 메커니즘 미설계 |
| Freshness Authority 없음 | glob + mtime 탐색 — canonical 최신 파일 결정 규칙 미존재 |
| Caddy write_file 403 | mcp_write_server approval_id 검증 미갱신 |

---

## 실행 계획

### Step 1 — 응급 복구 (비오 승인 후 즉시)

**목적**: projection_builder 최신화. 도미·제니가 보는 Projection을 S150 기준으로 갱신.

**PEC 2개 항목:**

| # | 확인 항목 | 결과 |
|---|---|---|
| P-1 | 파일명 `SESSION_CONTEXT_S150_FINAL.json` (glob 패턴 일치) | ✅ |
| P-2 | git commit 후 배포 (rollback 가능성 확보 — 실행 권한: 비오님) | 실행 시 수행 |

**SCP 명령:**
```powershell
scp C:\Users\chbo\Downloads\SESSION_CONTEXT_S150_FINAL.json root@159.203.125.1:/opt/arss/engine/arss-protocol/SESSION_CONTEXT_S150_FINAL.json
```

```powershell
ssh root@159.203.125.1 "cd /opt/arss/engine/arss-protocol && git add SESSION_CONTEXT_S150_FINAL.json && git commit -m 'feat: SESSION_CONTEXT_S150_FINAL 배포 — Projection 최신화 (S150)'"
```

---

### Phase A — Context Gateway 설계 (BRIEFING-DOMI-S150-PHASE-A)

**EAG 대상**: EAG-1 설계 승인  
**수신**: 도미  
**범위 엄격 제한** (Watchdog/Write Plane 제외):

#### A-1. Projection Freshness Authority ← 최우선

> "누가 최신 SESSION_CONTEXT를 결정하는가"

**현재 문제**: `glob("SESSION_CONTEXT_S*_FINAL.json")` + mtime 탐색  
→ 파일 혼재 시 오인 위험 (`S150_FINAL_fix.json`이 canonical로 오인)

**설계 방향 (캐디 안):**
```json
// SESSION_CONTEXT_POINTER.json (VPS 루트에 위치)
{
  "canonical": "SESSION_CONTEXT_S150_FINAL.json",
  "session": 150,
  "updated_at": "2026-05-24T00:00:00+09:00",
  "authority": "caddy"
}
```
- projection_builder가 POINTER 파일을 먼저 읽고 canonical 결정
- POINTER 파일 없으면 glob fallback (기존 동작 유지)

도미가 4개 방식 중 선택:
- `manifest 기반 latest pointer`
- `active_session pointer` ← 캐디 권장 (단순, 명확)
- `canonical_current.json alias`
- `monotonic session index validation`

#### A-2. SESSION_CONTEXT 최신성 기준

- 세션 종료 시 VPS 배포 의무화 조건 정의
- 캐디 session_close_rules 개정 대상 항목 명세

#### A-3. Shard write-back 원칙

- 어떤 shard가, 언제, 어떤 트리거로 갱신되는가
- 세션 종료 자동 갱신 대상 shard 선정 기준
- 캐디 write_file 403 해소 전 임시 운영 방안 (SCP 수동)

#### A-4. 역할별 Projection 범위 (role-scoped)

- 도미용 Projection: 설계 판단에 필요한 필드
- 제니용 Projection: 거버넌스·보안 감사에 필요한 필드
- 현재 `ALLOWED_TOP_KEYS` 14개 → 역할별 분화

#### A-5. Stale Projection 차단 규칙

- Freshness Authority 기반 stale 판정
- stale 시 도미·제니 동작 규칙 (PENDING 선언 vs 경고 후 계속)

---

### Phase B — Sandbox Watchdog 설계 (Phase A 완료 후)

```
보류. Phase A EAG 완료 후 착수.

내용 (예정):
  - Ticket FSM 자동 전이
  - 에이전트별 Session Boot Checklist
  - Caddy → Domi → Jeni → Beo 흐름
  - 자동 전이 조건
  - 비오 개입 최소화 경계
```

---

### Phase C — Write Plane 2-tier 설계 (Phase A 완료 후)

```
보류. Phase A EAG 완료 후 착수.

내용 (예정):
  - Tier 1: 비오 승인 쓰기 (캐디 제안 → 비오 승인 → 실행)
  - Tier 2: 격리 sandbox 자율 쓰기 (캐디 자율)
  - 운영 shard와 sandbox shard 분리
  - mcp_write_server.py 업데이트
```

---

## 전체 로드맵

```
[즉시]   Step 1   SCP → git commit → Projection 응급 최신화
                  PEC 완료 / 비오 승인 필요

[병렬]   Phase A  BRIEFING-DOMI-S150-PHASE-A 발행
                  A-1 Freshness Authority 우선 설계
                  → 캐디 IMPLEMENTABLE → 제니 TRUST_READY → EAG-1

[이후]   Phase B  Sandbox Watchdog (Phase A EAG 완료 후)
         Phase C  Write Plane 2-tier (Phase A EAG 완료 후)
```

---

## 3자 합의 서명

| 에이전트 | Step 1 | Phase A | Phase B/C 보류 |
|---|---|---|---|
| **도미** | ✅ 승인 | ✅ 즉시 착수 | ✅ |
| **제니** | ✅ 승인 | ✅ 즉시 착수 | ✅ |
| **캐디** | ✅ 승인 | ✅ 즉시 착수 | ✅ |

---

## PT 등록

**태스크 ID**: `PT-S150-CONTEXT-GATEWAY-ORCHESTRATION`  
**상태**: `EAG-1_PENDING` (Phase A 브리핑 발행 후 EAG-1 진입 예정)  
**우선순위**: HIGH  
**소유**: 도미(설계) → 캐디(IMPLEMENTABLE) → 제니(TRUST_READY) → 비오(EAG)

---

*생성: caddy / S150 / 2026-05-24*  
*파일 상태: DRAFT*
