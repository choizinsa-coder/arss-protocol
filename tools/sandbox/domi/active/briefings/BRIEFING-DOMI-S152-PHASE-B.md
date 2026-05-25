# BRIEFING-DOMI-S152-PHASE-B
## Context Gateway Phase B — Sandbox Watchdog 설계 의뢰

- **발행자:** 캐디 (S152)
- **수신자:** 도미
- **발행일:** 2026-05-25
- **분류:** 설계 의뢰 (EAG 전 단계)
- **연관 태스크:** PT-S150-CONTEXT-GATEWAY-ORCHESTRATION
- **참조:** BRIEFING-DOMI-S150-PHASE-A (Phase A 기반)

---

## 1. 배경 — Phase A 완료 상태

Phase A (S151 완료, 26/26 PASS)를 통해 다음이 구축되었다:

| 컴포넌트 | 경로 | 역할 |
|---------|------|------|
| `pointer_manager.py` | `tools/context_gateway/pointer_manager.py` | POINTER.json 읽기/검증 |
| `manifest_manager.py` | `tools/context_gateway/manifest_manager.py` | STALE_MANIFEST.json 읽기/생성 |
| `projection_builder.py` | `tools/projection_builder.py` | 역할별 Projection 생성 (pointer-first + role-scoped) |
| `SESSION_CONTEXT_POINTER.json` | VPS root | 정규 컨텍스트 포인터 |
| `SESSION_CONTEXT_STALE_MANIFEST.json` | VPS root | Staleness 신호판 |

### Phase A 설계 결정 (구속력 있음 — Phase B에서 반드시 준수)

| ID | 결정 |
|----|------|
| A1 | Pointer-first canonical load — SESSION_CONTEXT_POINTER.json 권위 |
| A2 | Close Bundle 3-way 일치 필수 (session_count / context_hash / updated_at) |
| A3 | Stale Manifest = 판단 차단용 신호판. **write_back은 Phase C로 이연** |
| A4 | 역할별 Projection — 도미/제니/캐디 필드 분화 |
| A5 | STALE_PROJECTION 차단 — 설계확정/TRUST_READY/EAG 금지 |

---

## 2. 현재 관찰된 문제 (Phase B 필요성 실증)

S152 세션 시작 시점, VPS 직접 확인 결과:

```json
// SESSION_CONTEXT_POINTER.json (실측)
{
  "current_session": 150,      // ← S151 완료 후에도 갱신되지 않음
  "context_hash": "6f3cbc7f...",
  "updated_at": "2026-05-24T19:44:56..."
}

// SESSION_CONTEXT_STALE_MANIFEST.json (실측)
{
  "manifest_session": 150,
  "projection_status": "fresh",   // ← 실제로는 S151 기준 stale
  "write_back_allowed": false,
  "blocking_flags": []            // ← 차단 신호 없음 — 위험
}
```

**문제:** S151이 완료되어 `SESSION_CONTEXT_S151_FINAL.json`이 VPS에 존재하나, POINTER는 여전히 S150을 가리킨다. Manifest는 `fresh`로 표시되어 있으나 실제로는 stale 상태다. Watchdog 없이는 이 불일치를 자동 감지·차단할 수단이 없다.

또한, S150 3자 합의에서 확인된 구조적 취약점:

> _"Projection Freshness Authority 설계 필요 — glob+mtime 구조적 취약점 확인"_

`glob + mtime` 기반 staleness 탐지는 파일 timestamp 조작, 동시 쓰기, 또는 VPS 재배포 타이밍 이슈에 취약하다. Phase B는 이 취약점을 해소하는 신뢰 가능한 Freshness Authority 메커니즘을 설계해야 한다.

---

## 3. Phase B 설계 범위

### 핵심 목표

> **POINTER.json과 실제 VPS 배포 상태 간의 불일치를 자동으로 탐지하고, STALE_MANIFEST blocking_flags를 정확히 갱신하여 판단 차단을 보장한다.**

### 포함 범위 (In-Scope)

1. **Watchdog 트리거 메커니즘** — 어떤 이벤트/조건이 Watchdog 실행을 유발하는가
2. **Freshness Authority 설계** — glob+mtime 취약점을 대체할 신뢰 가능한 staleness 판정 기준
3. **STALE_MANIFEST 갱신 로직** — `blocking_flags`, `projection_status`, `stale_blocked_actions` 필드 자동 갱신
4. **Close Bundle 검증 통합** — A2 결정(3-way 일치)과 Watchdog 연동 방식
5. **역할별 차단 전파** — `role_projection_status` 필드의 stale 전파 및 차단 범위
6. **Watchdog 실행 주체/권한** — 자율 실행 가능 범위 vs. Beo 개입 필요 범위

### 제외 범위 (Out-of-Scope — Phase C)

- POINTER.json의 `current_session` 자동 업데이트 (write_back) → **Phase C 전담**
- Write Plane 2-tier 구조 설계 → **Phase C 전담**
- Watchdog이 직접 POINTER.json을 수정하는 모든 행위 → **금지 (A3 위반)**

---

## 4. 도미에게 요청하는 설계 결정 항목

### B-1. Watchdog 트리거 전략
다음 중 어떤 트리거 모델이 적합한가:
- (a) **주기적 폴링** — cron/systemd timer 기반, 일정 주기로 VPS 상태 검사
- (b) **이벤트 기반** — SESSION_CONTEXT 파일 배포 시 명시적 Watchdog 호출
- (c) **세션 오픈 시 1회** — 캐디 세션 시작마다 PRE-OUTPUT CHECK의 일부로 실행
- (d) **복합** — 위 조합

### B-2. Freshness Authority 기준
`glob + mtime` 대안으로, 다음 중 어떤 기준이 신뢰 가능한가:
- (a) **session_count 비교** — POINTER.current_session vs. VPS상 최신 `SESSION_CONTEXT_S{n}_FINAL.json`의 n
- (b) **context_hash 비교** — POINTER.context_hash vs. 실제 파일 해시 재계산
- (c) **Close Bundle 재검증** — A2 기준 3-way 재계산으로 불일치 탐지
- (d) **복합 판정** — 위 중 2개 이상 동시 충족 필요

### B-3. STALE_MANIFEST 갱신 권한
Watchdog은 STALE_MANIFEST를 **직접 쓸 수 있는가**, 아니면 **신호만 생성하고 별도 승인 후 갱신**되는가:
- Phase A에서 `write_back_allowed: false`로 설정됨
- Watchdog의 STALE_MANIFEST 갱신은 write_back과 동일 성격인가, 다른 성격인가?

### B-4. 역할별 차단 전파 범위
STALE 탐지 시 `role_projection_status`를 일괄 stale 처리할 것인가, 역할별로 차등 적용할 것인가:
- 모든 역할(도미/제니/캐디) 동시 차단 vs. 역할 의존성 기반 순차 차단

### B-5. Watchdog 컴포넌트 위치 및 구조
- 독립 모듈(`tools/context_gateway/watchdog.py`)로 설계할 것인가
- 기존 `manifest_manager.py`에 통합할 것인가
- systemd service로 상시 실행할 것인가, 호출형으로 설계할 것인가

---

## 5. 캐디의 사전 판단 (도미 설계 시 참고)

다음은 캐디의 기술적 관찰이며, 도미의 설계 권한을 침범하지 않는 범위의 맥락 정보다:

- **B-1 판단:** 세션 오픈 시 실행(c)이 현 아키텍처에 가장 자연스럽게 통합된다. PRE-OUTPUT MANDATORY CHECK의 일부로 편입 가능하며, 상시 폴링(a)은 VPS 리소스 사용 측면에서 불필요할 수 있다.
- **B-2 판단:** session_count 비교(a)가 구현이 단순하고 신뢰도가 높다. VPS상 파일명 패턴 `SESSION_CONTEXT_S{n}_FINAL.json`에서 n 추출은 glob+mtime보다 조작 저항성이 높다.
- **B-3 판단:** 이것이 Phase B의 핵심 설계 결정이다. Watchdog의 STALE_MANIFEST 갱신은 write_back(POINTER 업데이트)과 다른 성격이므로, 별도 허용 범주로 정의 가능할 수 있다. 단, 도미의 명확한 결정이 필요하다.

---

## 6. 산출물 요청

도미는 다음을 포함한 Phase B 설계를 제출해 주기 바란다:

1. **B-1 ~ B-5 각 항목에 대한 설계 결정**
2. **Watchdog 컴포넌트 구조 및 인터페이스 정의** (함수 시그니처 수준)
3. **STALE_MANIFEST 갱신 시 변경될 필드 목록 및 값 정의**
4. **Phase A 결정(A1~A5)과의 정합성 확인**
5. **Phase C와의 경계 명시** (Watchdog이 절대 침범하지 않을 영역)

---

## 7. 제약 사항

- **A3 위반 금지:** Watchdog은 `SESSION_CONTEXT_POINTER.json`을 수정하지 않는다
- **A5 준수:** STALE 상태에서 설계확정/TRUST_READY/EAG 진행 불가 규칙은 Phase B에서도 유지
- **Close Bundle 권위 유지:** A2 기준은 Phase B에서 약화되지 않는다
- **단일 책임:** Watchdog은 탐지와 신호 갱신만 담당. POINTER 갱신은 Phase C 전담

---

*본 브리핑은 캐디(S152)가 작성하였으며, 비오(Joshua)의 EAG 승인 후 VPS 배포됩니다.*
