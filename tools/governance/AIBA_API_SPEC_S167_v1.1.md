# AIBA 전체 API 스펙 통합 문서
**버전**: v1.1  
**작성 세션**: S167  
**작성일**: 2026-05-29 (KST)  
**작성자**: Caddy  
**상태**: COMPLETE  
**범위 확정**: 비오(Joshua) S167 — API 명세(Endpoint/Method/Schema/Auth/State Model/Permission Boundary)로 한정  
**변경 이력**: v1.0→v1.1 Authority Boundary Matrix 섹션 추가 (도미 CHK-02/03 Minor 권고 반영)

---

## 목차

1. [개요](#1-개요)
2. [인프라 구성](#2-인프라-구성)
3. [인증 체계](#3-인증-체계)
4. [Status Server API (포트 8000)](#4-status-server-api-포트-8000)
5. [MCP Write Server API (포트 8444)](#5-mcp-write-server-api-포트-8444)
6. [MCP HTTP Bridge (포트 8443)](#6-mcp-http-bridge-포트-8443)
7. [ARSS Protocol MCP 도구 목록](#7-arss-protocol-mcp-도구-목록)
8. [Observation Server (포트 8446)](#8-observation-server-포트-8446)
9. [ARSS Generator API (포트 8001)](#9-arss-generator-api-포트-8001)
10. [공통 에러 코드](#10-공통-에러-코드)
11. [거버넌스 제약](#11-거버넌스-제약)
12. [Authority Boundary Matrix](#12-authority-boundary-matrix)
13. [Known Infrastructure Gaps](#13-known-infrastructure-gaps)

---

## 1. 개요

AIBA (AI-Based Agent) 시스템은 VPS (`159.203.125.1`)에서 운영되는 복수의 HTTP 서버로 구성됩니다.  
각 서버는 역할 경계와 거버넌스 규칙에 따라 분리된 API Surface를 제공합니다.

| 서버 | 파일 | 내부 포트 | 역할 | 활성 여부 |
|---|---|---|---|---|
| Status Server | `aiba_status_server.py` | 8000 | SESSION_CONTEXT 조회·갱신, RPU 발행, Approval Pool | ✅ ACTIVE |
| MCP Write Server | `tools/mcp/mcp_write_server.py` | 8444 | Write Plane (Tier1/Tier2) | ✅ ACTIVE |
| MCP HTTP Bridge | `tools/mcp/mcp_http_bridge.py` | 8443 | ARSS Protocol MCP 커넥터 진입점 | ✅ ACTIVE |
| Observation Server | `tools/observation_server.py` | 8446 | 역할별 Projection + Sandbox Write Gate | ✅ ACTIVE |
| ARSS Generator | `arss_generator_v1.py` | 8001 | RPU 후보 생성 (Legacy/Standalone) | ⚠️ LEGACY |

모든 서버는 nginx 역방향 프록시를 통해 외부 접근이 제어됩니다.

---

## 2. 인프라 구성

```
외부 클라이언트 (claude.ai / n8n)
         │
         ▼
     nginx
    ┌─────┬─────────────────────┐
    │     │                     │
    ▼     ▼                     ▼
  8443  8445               (8000/8444)
Bridge  Obs(nginx)          직접 또는
   │        │               nginx 경유
   ▼        ▼
 8443     8446
Bridge  Obs Server
   │
   ├─ 8000 (Status Server)
   └─ 8444 (Write Server)
```

**VPS 기본 경로**: `/opt/arss/engine/arss-protocol/`  
**Sandbox 기본 경로**: `/opt/arss/engine/arss-protocol/tools/sandbox/`

---

## 3. 인증 체계

### 3-1. Status Server Bearer Token

에이전트별 Bearer Token (`Authorization: Bearer <token>`)

| 에이전트 | 환경변수 | WRITE 권한 |
|---|---|---|
| `caddy` | `AIBA_TOKEN_CADDY` | ✅ |
| `domi` | `AIBA_TOKEN_DOMI` | ❌ |
| `jeni` | `AIBA_TOKEN_JENI` | ❌ |
| `system` | `AIBA_TOKEN_SYSTEM` | ✅ |

### 3-2. HMAC 서명 (일부 엔드포인트)

`POST /status/update`에서 요구:
```
X-AIBA-Signature: <HMAC-SHA256(body, HMAC_SECRET)>
```
환경변수: `HMAC_SECRET`

### 3-3. MCP Bridge — 내부 HMAC

Bridge가 ReadOnlyServer 호출 시 3요소(actor_id, connector_identity, nonce)로 자동 생성  
환경변수: `AIBA_READ_HMAC_SECRET`

### 3-4. Observation Server — 에이전트별 Bearer Token (SHA256 해시 기반)

토큰은 raw 값을 서버에 저장하지 않음 — SHA256 해시만 보관  
TTL 최대 12시간 (`TOKEN_TTL_MAX = 43200`)

| 에이전트 | 접근 엔드포인트 |
|---|---|
| `domi` | `/domi-view/*` |
| `jeni` | `/jeni-view/*` |

토큰 발급: `POST /internal/token/register` (loopback + 비오님 only)  
발급 후 서버 내 raw token 복원 불가 — 1회 응답 반환만

### 3-5. ARSS Generator Bearer Token

`caddy` Bearer Token (`AIBA_TOKEN_CADDY`) 단일 사용

### 3-6. 인증 없음 (Public Endpoints)

- `GET /health` (Status Server)
- `GET /v1/system/time`
- `GET /health` (Write Server)
- `GET /bridge/health` (Bridge)

---

## 4. Status Server API (포트 8000)

**버전**: v0.9  
**서비스 파일**: `aiba-status.service`  
**환경 변수**: `.env` 파일 주입

---

### 4-1. GET /health

**인증**: 없음  
**응답 (200)**:
```json
{
  "status": "ok",
  "server": "aiba_status_server",
  "version": "v0.9",
  "timestamp": 1748500000,
  "cpu_percent": 3.2,
  "memory": { "total_mb": 1024.0, "used_mb": 512.3, "percent": 50.0 },
  "disk": { "total_gb": 49.0, "used_gb": 7.8, "percent": 17.0 }
}
```

---

### 4-2. GET /v1/system/time

**인증**: 없음  
**용도**: Session Time Lock 획득 (DIS-037)  
**계약 스펙**: UTS v1.0-Rev.A (PT-S71-001 EAG-3)

**응답 (200)**:
```json
{
  "ok": true,
  "source": "AIBA_STATUS_SERVER_CLOCK",
  "timezone": "Asia/Seoul",
  "timestamp": "2026-05-29T15:20:43.469+09:00",
  "epoch_ms": 1748500000000,
  "current_kst": "2026-05-29T15:20:43+09:00",
  "current_utc": "2026-05-29T06:20:43Z",
  "utc_offset": "+09:00",
  "unix_timestamp": 1748500000
}
```

> **주의**: `session_time_lock` 계산 시 `timestamp` 필드 사용. `generated_at` 기반 날짜 판단 금지 (DIS-037).

---

### 4-3. GET /approval-token

**인증**: `caddy` only  
**용도**: EAG 승인 토큰 조회  
**응답 (200)**: `.approval_token` 파일 내용  
**응답 (404)**: 파일 없음 / **응답 (410)**: 만료 / **응답 (422)**: 만료일 누락

---

### 4-4. GET /session/current

**인증**: Bearer (모든 에이전트)  
**응답 (200)**: `{ "status": "ok", "session_count": 167 }`

---

### 4-5. GET /status

**인증**: Bearer (모든 에이전트)  
**응답 (200)**: `{ "status": "ok", "data": { /* SESSION_CONTEXT 전체 */ } }`

---

### 4-6. POST /status/update

**인증**: Bearer (WRITE 권한) + `X-AIBA-Signature`  
**용도**: SESSION_CONTEXT.json 전체 교체 (부분 업데이트 미지원)

---

### 4-7. GET /file-hash

**인증**: Bearer (모든 에이전트)

**Query Parameters**:

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `path` | SESSION_CONTEXT.json | 대상 파일 절대경로 (BASE_DIR 내부만 허용) |
| `content` | `false` | `true` 시 파일 내용도 함께 반환 |

---

### 4-8. GET /session-context

**인증**: Bearer (모든 에이전트)  
**응답 (200)**: `{ "status": "ok", "data": {...}, "sha256": "...", "size": 65536 }`

---

### 4-9. GET /sync-metadata

**인증**: Bearer (모든 에이전트)  
**응답 (200)**: `{ "status": "ok", "data": { /* sync_metadata.json */ } }`

---

### 4-10. POST /sync-metadata

**인증**: Bearer (WRITE 권한)  
**응답 (200)**: `{ "status": "ok", "message": "sync_metadata updated" }`

---

### 4-11. POST /rpu/issue

**인증**: Bearer (WRITE 권한)  
**용도**: RPU 발행 — 5-Step Orchestrator (LESSON-011/013)

**Request Body**:
```json
{
  "actor_id": "caddy",
  "content": "...",
  "event_type": "task_completed",
  "session_id": "AIBA-S167",
  "source_ref": "PT-S167-001",
  "approval_id": "EAG-1-S167",
  "dry_run": false
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `content` | ✅ | RPU 내용 |
| `event_type` | ✅ | INTERPRETATION_RULE 허용 목록 내 값 |
| `session_id` | ✅ | `AIBA-S{n}` 형식 |
| `actor_id` | ❌ | 발행 에이전트 |
| `source_ref` | ❌ | 참조 태스크 ID |
| `approval_id` | ❌ | EAG 승인 ID — 제공 시 R1~R4 검증 강제 |
| `dry_run` | ❌ | `true` 시 Step 5 후검증 건너뜀 |

**5-Step 처리 흐름**:

```
R1~R4: approval_id 검증 (존재/binding/scope/integrity)
Step 1: 필수 필드 완결성 검사
Step 2: event_type allowlist 확인 (INTERPRETATION_RULE.json)
Step 3: PEC 캡처 (chain_tip + 파일 존재 확인)
Step 4: rpu_atomic_issuer.py subprocess 호출
Step 5: vps_verifier_bridge.py 후검증 (dry_run=true 시 skip)
```

**응답 (200, SUCCESS)**:
```json
{
  "status": "SUCCESS",
  "rpu_id": "RPU-0044",
  "chain_tip": "abcd1234...",
  "publication_state": "PUSHED",
  "verifier_result": "PASS",
  "pec_captured_at": "2026-05-29T06:20:43Z",
  "dry_run": false
}
```

---

### 4-12. GET /approval-pool/ready

**인증**: `caddy` only  
**응답 (200)**: `{ "status": "READY", "approval_id": "...", "event_hash": "...", "payload": {...} }` 또는 `{ "status": "POOL_EMPTY" }`

---

### 4-13. POST /approval-pool/add

**인증**: `caddy` only  
**Request Body**: `{ "session_id": "AIBA-S167" }`  
**응답 (200)**: `{ "status": "registered", ... }` / **(409)**: 이미 READY 또는 CONSUMED

---

### 4-14. POST /approval-pool/consume

**인증**: `caddy` only  
**Request Body**: `{ "approval_id": "EAG-1-S167" }`  
**응답 (200)**: `{ "status": "CONSUMED", "consumed_at_kst": "..." }` / **(409)**: READY 상태 아님

---

## 5. MCP Write Server API (포트 8444)

**버전**: v3.0.0 (S164)  
**접근**: loopback `127.0.0.1:8444` 전용 — MCP HTTP Bridge 경유

---

### 5-1. GET /health

**인증**: 없음  
**응답 (200)**: `{ "status": "ok", "write_plane_state": "NORMAL", "version": "3.0.0" }`

---

### 5-2. POST /mcp/write — write_file

**Content-Type**: `application/json`

```json
{
  "tool": "write_file",
  "params": {
    "approval_id": "EAG-1-S167",
    "target_path": "/opt/arss/engine/arss-protocol/...",
    "content": "..."
  }
}
```

**Tier 분기**:
- `target_path`가 Tier2 sandbox → `approval_id` 불필요
- 그 외 → Tier1, `approval_id` 필수 (CONTRACT-04)
- `os.path.realpath` 기반 — symlink/`..` 우회 차단

---

### 5-3. POST /mcp/write — get_write_plane_state

```json
{ "tool": "get_write_plane_state", "params": {} }
```
**응답 (200)**: `{ "ok": true, "write_plane_state": "NORMAL" }`

**상태값**:

| 상태 | 의미 |
|---|---|
| `NORMAL` | Tier1/Tier2 모두 정상 |
| `LOCKED_TIER1` | Tier1 잠금, Tier2만 허용 |
| `LOCKED_ALL` | 전체 잠금 |
| `RECOVERY` | 복구 모드 |

---

### 5-4. POST /internal/state/set

**loopback 전용**  
**Request Body**: `{ "state": "NORMAL", "reason": "..." }`

---

## 6. MCP HTTP Bridge (포트 8443)

**버전**: v2.2.0 (S139)  
**프로토콜**: MCP Streamable HTTP (JSON-RPC 2.0)

---

### 6-1. GET /bridge/health

**인증**: 없음  
**응답**: `{ "bridge_state": "ACTIVE", "containment": false, "version": "2.2.0" }`

---

### 6-2. GET /mcp — SSE Stream

SSE (Server-Sent Events) 연결 유지  
`Content-Type: text/event-stream`  
heartbeat 주기: 15초

---

### 6-3. POST /mcp — JSON-RPC

**지원 메서드**:

| 메서드 | 설명 |
|---|---|
| `initialize` | MCP 프로토콜 초기화 |
| `tools/list` | 도구 목록 조회 |
| `tools/call` | 도구 실행 |

**Request 예시 (tools/call)**:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tools/call",
  "params": {
    "name": "read_file",
    "arguments": {
      "actor_id": "caddy",
      "path": "/opt/arss/engine/arss-protocol/SESSION_CONTEXT_POINTER.json",
      "purpose": "OBSERVATION"
    }
  }
}
```

**Containment 차단 에러**:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "error": { "code": -32000, "message": "AIBA containment active" }
}
```

---

## 7. ARSS Protocol MCP 도구 목록

총 13종.

### 7-1. 기본 도구 (2종)

| 도구 | 설명 |
|---|---|
| `ping` | Bridge 연결 확인 → "pong" |
| `get_load_state` | Bridge 상태 / Containment 상태 조회 |

### 7-2. READ 도구 — 파일시스템/서비스 계열 (5종)

공통 필수 파라미터: `actor_id` (domi/jeni/caddy), `purpose`

**허용 `purpose` 값**:
`OBSERVATION | EVIDENCE_INSPECTION | AUDIT_INSPECTION | CONSISTENCY_CHECK | STALE_DETECTION`

| 도구 | 추가 파라미터 | 제약 |
|---|---|---|
| `read_file` | `path` | whitelist 경로 전용 |
| `list_dir` | `path` | depth=1, recursive 금지 |
| `grep_scoped` | `path`, `pattern`, `max_results`(선택) | depth=2 |
| `read_log` | `path`, `tail_lines` | 최대 200줄 |
| `check_service_state` | `service_name` | 허용: nginx, aiba-mcp-bridge |

### 7-3. READ 도구 — 메타데이터/감사 계열 (4종)

| 도구 | 추가 파라미터 | 제약 |
|---|---|---|
| `read_pytest_result` | `artifact_path` | 실행 아님, 읽기만 |
| `read_audit_event` | `log_path`, `event_range` | 최대 100건, bulk dump 금지 |
| `read_metadata` | `path` | SESSION_CONTEXT / SESSION_BOOT / sync metadata |
| `get_runtime_snapshot` | 없음 | 사전 정의 projection만 |

### 7-4. WRITE 도구 (2종) — caddy only

| 도구 | 필수 파라미터 | 제약 |
|---|---|---|
| `write_file` | `actor_id`, `approval_id`, `target_path`, `content` | payload 상한 65,536B, 30초 timeout |
| `get_write_plane_state` | `actor_id` | 조회 전용 |

---

## 8. Observation Server (포트 8446)

**파일**: `tools/observation_server.py`  
**서비스**: `aiba-observation.service`  
**nginx 외부 포트**: 8445 → 내부 8446  
**권한 원칙**: OBSERVATION_ONLY + SANDBOX_WRITE_GATE  
**설계 근거**: BRIEFING-DOMI-S142-DESIGN-REQUEST-FINAL

---

### 8-1. 인증 방식

에이전트별 Bearer Token (`Authorization: Bearer <token>`)

- raw token → SHA256 해시 저장 (`tools/sandbox/.tokens`, chmod 600)
- 만료 후 자동 무효, TTL 최대 43,200초(12h)
- 토큰 발급: `POST /internal/token/register` (loopback + 비오님 전용)
- 발급 응답에만 raw token 1회 반환 → 이후 서버 복원 불가

**에러 코드**:

| 코드 | 이유 |
|---|---|
| `TOKEN_REQUIRED` | Authorization 헤더 없음 |
| `TOKEN_EXPIRED` | 만료 |
| `TOKEN_REVOKED` | 폐기됨 |
| `TOKEN_AGENT_MISMATCH` | 토큰-에이전트 불일치 → Fail-Closed 발동 |

---

### 8-2. GET /domi-view/projection

**인증**: domi token  
**용도**: Domi용 Context Projection (역할별 필드 서브셋)

**응답 (200, fresh)**:
```json
{
  /* projection_builder.get_projection() 결과 */
}
```

**응답 (200, stale)**:
```json
{
  "stale": true,
  "message": "...",
  "execution_allowed": false
}
```

모든 응답에 헤더 포함:
```
X-Authority: OBSERVATION_ONLY_NO_EXECUTION
```

---

### 8-3. GET /jeni-view/projection

**인증**: jeni token  
**응답 구조**: `/domi-view/projection`과 동일, Jeni용 필드 서브셋

---

### 8-4. GET /domi-view/sandbox/index

**인증**: domi token  
**응답 (200)**: `{ "files": ["file1.json", ...], "agent": "domi", "execution_allowed": false }`

---

### 8-5. GET /jeni-view/sandbox/index

**인증**: jeni token  
**응답 구조**: domi와 동일

---

### 8-6. POST /domi-view/sandbox

**인증**: domi token  
**용도**: Domi Sandbox 파일 쓰기 (SANDBOX_WRITE_GATE)

**Request Body**:
```json
{
  "filename": "design_draft.json",
  "content": "...",
  "status": "DRAFT",
  "safe_pass": false
}
```

| 필드 | 설명 |
|---|---|
| `filename` | 대상 파일명 |
| `content` | 파일 내용 (문자열) |
| `status` | 파일 상태 (`DRAFT` 등) |
| `safe_pass` | `sandbox_validator.py` 안전 통과 요청 |

**쓰기 경로**: `tools/sandbox/domi/active/<filename>`  
**응답 (200)**: `{ "result": "ALLOW", "filename": "...", "execution_allowed": false }`

**실패 응답**: `{ "error": "REASON", "execution_allowed": false }`

> **Fail-Closed 발동 조건**: `PATH_OUTSIDE_SANDBOX`, `SYMLINK_DENIED`, `FORBIDDEN_EXTENSION`, `CROSS_OVERWRITE_DENIED`, `TOKEN_AGENT_MISMATCH`

---

### 8-7. POST /jeni-view/sandbox

**인증**: jeni token  
**응답 구조**: domi와 동일, 쓰기 경로: `tools/sandbox/jeni/active/<filename>`

---

### 8-8. POST /internal/token/register

**접근**: loopback only (`127.0.0.1`)  
**용도**: 비오님 전용 토큰 발급/교체

**Request Body**:
```json
{
  "actor": "beo",
  "approval_phrase": "BEO_APPROVE_TOKEN_REGISTER",
  "agent": "domi",
  "ttl_seconds": 43200
}
```

| 필드 | 허용값 |
|---|---|
| `actor` | `"beo"` 고정 |
| `approval_phrase` | `"BEO_APPROVE_TOKEN_REGISTER"` |
| `agent` | `"domi"` 또는 `"jeni"` |
| `ttl_seconds` | 최대 43200 |

**응답 (200)**:
```json
{
  "ok": true,
  "agent": "domi",
  "token": "<raw_token>",
  "expires_at": "2026-05-29T27:20:43+09:00",
  "token_hash_prefix": "abcd1234...",
  "execution_allowed": false
}
```

> `token` 필드는 이 응답에서만 반환 — 서버 내 raw token 미보관.

---

### 8-9. POST /internal/observation/unlock

**접근**: loopback only  
**용도**: Fail-Closed 해제 (비오님 전용)

**Request Body**:
```json
{
  "actor": "beo",
  "approval_phrase": "BEO_APPROVE_OBSERVATION_UNLOCK",
  "incident_id": "INC-2026-001",
  "jeni_trust_revalidation": "PASS",
  "caddy_incident_report": "PRESENT",
  "new_token_rotation": "DONE"
}
```

**해제 조건 (전항목 충족 필수)**:

| 조건 | 필요값 |
|---|---|
| `actor` | `"beo"` |
| `approval_phrase` | `"BEO_APPROVE_OBSERVATION_UNLOCK"` |
| `incident_id` | 비어있지 않은 값 |
| `jeni_trust_revalidation` | `"PASS"` |
| `caddy_incident_report` | `"PRESENT"` |
| `new_token_rotation` | `"DONE"` |

**응답 (200)**:
```json
{
  "result": "OBSERVATION_UNLOCKED",
  "incident_id": "INC-2026-001",
  "projection_cache_invalidated": true,
  "execution_allowed": false
}
```

---

### 8-10. Observation Server 상태 모델

```
UNLOCKED ──(보안 위반 자동)──▶ LOCKED (observation_locked=true)
                                   │
                   ◀──(비오님 해제: 6조건)──┘
```

**LOCKED 시 동작**: 모든 GET/POST 요청 → `503 OBSERVATION_LOCKED`

---

## 9. ARSS Generator API (포트 8001)

**파일**: `arss_generator_v1.py`  
**기본 포트**: 8001 (환경변수 `GENERATOR_PORT` 재정의 가능)  
**접근**: loopback `127.0.0.1:8001`

> **⚠️ LEGACY 상태**: 현행 표준 RPU 발행 경로는 `POST /rpu/issue` (Status Server).  
> `arss_generator_v1.py`는 독립 실행형 레거시 RPU 후보 생성기로, 현재 활성 여부 별도 확인 필요.  
> 태스크 `PT-LEGACY-AUTO-023` (PLANNED) 기반 문서화 대상.

---

### 9-1. GET /health

**인증**: 없음  
**응답 (200)**: `{ "status": "ok", "version": "arss_generator_v1" }`

---

### 9-2. POST /generate

**인증**: `caddy` Bearer Token (`AIBA_TOKEN_CADDY`)  
**용도**: RPU 후보 객체 생성 + verifier 검증  
**Content-Type**: `application/json`

**Request Body**:
```json
{
  "actor_id": "caddy",
  "event_type": "task_completed",
  "content": "...",
  "prev_chain_hash": "abcd1234...abcd1234...abcd1234...abcd1234..."
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `event_type` | ✅ | INTERPRETATION_RULE 허용 목록 내 값 |
| `content` | ✅ | RPU 내용 |
| `prev_chain_hash` | ✅ | 64자 hex SHA256 (이전 chain_hash) |
| `actor_id` | ✅ | 빈 문자열 허용 (자동화 시나리오 대응) |

**처리 흐름**:
```
validate_request() → build_rpu() → verify_candidate_rpu(subprocess) → persistence_allowed 반환
```

**응답 (200, PASS)**:
```json
{
  "status": "PASS",
  "candidate_rpu": {
    "schema_version": "ARSS-RPU-1.0",
    "rpu_id": "<UUIDv7>",
    "timestamp": "2026-05-29T06:20:43.000000Z",
    "actor_id": "caddy",
    "payload": {
      "event_type": "task_completed",
      "content": "..."
    },
    "chain": {
      "payload_hash": "<sha256>",
      "prev_chain_hash": "<sha256>",
      "chain_hash": "<sha256>"
    },
    "governance_context": {
      "policy_id": "ARSS_HUB_PROTOCOL_v1.2",
      "authority_root": "Beo",
      "jurisdiction": "AIBA_GLOBAL"
    }
  },
  "persistence_allowed": true
}
```

**응답 (400)**: `ValidationError` — 필드 누락, `prev_chain_hash` 형식 오류, event_type 미허용  
**응답 (422)**: `VerificationError` — verifier subprocess 실패  
**응답 (500)**: 내부 오류

> **중요**: `persistence_allowed: true`가 반환되어도 파일 저장·GitHub push는 상위 실행 계층 책임.  
> Generator는 후보 생성 + 검증만 수행. 영속화 금지.

**해시 알고리즘 (IMMUTABLE — LESSON-005)**:
```
payload_hash  = SHA256(canonical_json(payload))
chain_hash    = SHA256((prev_chain_hash + ":" + payload_hash).encode("utf-8"))
canonical_json = json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))
```

---

## 10. 공통 에러 코드

### Status Server

| HTTP | 의미 |
|---|---|
| 400 | 잘못된 요청 (필드 누락, 잘못된 JSON) |
| 401 | Bearer Token 누락 또는 불일치 |
| 403 | WRITE 권한 없음 / HMAC 불일치 / 허용 경로 외 |
| 404 | 파일 또는 리소스 없음 |
| 409 | 상태 충돌 |
| 410 | 토큰 만료 |
| 422 | 처리 불가 (event_type 미허용 등) |
| 500 | 서버 내부 오류 |

### Observation Server

| HTTP | 의미 |
|---|---|
| 401 | TOKEN_REQUIRED 또는 TOKEN_EXPIRED |
| 403 | TOKEN_REVOKED 또는 TOKEN_AGENT_MISMATCH |
| 404 | ENDPOINT_NOT_FOUND |
| 413 | REQUEST_TOO_LARGE (body > 64KB) |
| 503 | OBSERVATION_LOCKED (Fail-Closed 발동) |

### MCP Bridge (JSON-RPC)

| 코드 | 의미 |
|---|---|
| `-32601` | Method not found |
| `-32000` | Containment ACTIVE |
| `isError: true` | 도구 실행 실패 |

---

## 11. 거버넌스 제약

### 11-1. READ 도구 허용 Purpose

| Purpose | 허용 |
|---|---|
| `OBSERVATION` | ✅ |
| `EVIDENCE_INSPECTION` | ✅ |
| `AUDIT_INSPECTION` | ✅ |
| `CONSISTENCY_CHECK` | ✅ |
| `STALE_DETECTION` | ✅ |
| `EXECUTION_COORDINATION` | ❌ |
| `DEPLOYMENT_STEERING` | ❌ |
| `RUNTIME_CONTROL` | ❌ |
| `MUTATION_PREPARATION` | ❌ |
| `APPROVAL_SUBSTITUTION` | ❌ |

근거: `tools/governance/MCP_READ_CONSTANTS_REGISTRY_v1.0.json` (PT-S139)

### 11-2. Write Plane Tier 정책

**Tier2 허용 경로** (`tier_router.py` 기준, `os.path.realpath` 적용):

| 경로 | 설명 |
|---|---|
| `tools/sandbox/` | Domi/Jeni Sandbox 작업 영역 |
| `tools/tmp/` | 임시 파일 영역 |
| `tests/sandbox/` | 테스트용 Sandbox |

- Tier2: `approval_id` 불필요, Caddy 자율 쓰기
- Tier1: 위 경로 외 전체, `approval_id` 필수 (EAG 승인)
- symlink / `..` 우회 → `realpath` 변환 후 차단

### 11-3. RPU 발행 제약

- `event_type` → INTERPRETATION_RULE.json 허용 목록 (LESSON-013)
- `approval_id` 제공 시 R1~R4 검증 강제 (R4: payload integrity hash)
- `dry_run=true` → Step 5 건너뜀, 실제 체인 변경 발생 주의

### 11-4. Generator API 관계

| 경로 | 역할 | 현행 표준 |
|---|---|---|
| `POST /generate` (`arss_generator_v1.py`) | RPU 후보 생성 + 검증 (영속화 없음) | ❌ LEGACY |
| `POST /rpu/issue` (`aiba_status_server.py`) | RPU 발행 전 과정 (5-Step) | ✅ 현행 표준 |

### 11-5. Observation Server 실행 경계

- `execution_allowed: false` 헤더/필드 — 모든 응답에 포함
- Sandbox 파일 쓰기는 허용이나 실행 금지 (OBSERVATION_ONLY + SANDBOX_WRITE_GATE)
- Fail-Closed 발동 시 비오님 6조건 해제 필요

---

## 12. Authority Boundary Matrix

> 도미 CHK-02/03 권고 반영 — ACCESS / AUTHORITY / APPROVAL 3단 분리

AIBA에서 반복적으로 확인된 원칙:

```
API 호출 가능 (ACCESS)
        ≠
권한 보유 (AUTHORITY)
        ≠
실행 승인 (APPROVAL)
```

---

### 12-1. 에이전트별 API Access 매트릭스

| 기능 | Domi | Jeni | Caddy | System | Beo |
|---|---|---|---|---|---|
| MCP READ 도구 (9종) | ✅ | ✅ | ✅ | ❌ | — |
| MCP WRITE — `write_file` | ❌ | ❌ | ✅ | ❌ | — |
| MCP WRITE — `get_write_plane_state` | ❌ | ❌ | ✅ | ❌ | — |
| Observation `/projection` | ✅ domi only | ✅ jeni only | ❌ | ❌ | — |
| Observation `/sandbox` (write) | ✅ domi only | ✅ jeni only | ❌ | ❌ | — |
| Status Server READ (Bearer) | ✅ | ✅ | ✅ | ✅ | — |
| Status Server WRITE (`/status/update`, `/sync-metadata POST`) | ❌ | ❌ | ✅ | ✅ | — |
| `POST /rpu/issue` | ❌ | ❌ | ✅ | ✅ | — |
| Approval Pool (`/add`, `/ready`, `/consume`) | ❌ | ❌ | ✅ | ❌ | — |
| Write Plane 상태 수동 변경 (`/internal/state/set`) | ❌ | ❌ | ❌ | ❌ | ✅ loopback |
| Observation Fail-Closed 해제 (`/internal/observation/unlock`) | ❌ | ❌ | ❌ | ❌ | ✅ loopback |
| Token 발급 (`/internal/token/register`) | ❌ | ❌ | ❌ | ❌ | ✅ loopback |

---

### 12-2. Access / Authority / Approval 분리 정의

| 계층 | 정의 | 예시 |
|---|---|---|
| **ACCESS** | API 엔드포인트 호출 가능 여부 (인증 토큰 보유) | Caddy가 `POST /rpu/issue`를 호출할 수 있음 |
| **AUTHORITY** | 해당 작업을 수행할 역할 권한 보유 여부 | Caddy는 RPU 발행 실행자 역할을 가짐 |
| **APPROVAL** | EAG(비오님 명시 승인) 또는 `approval_id` 검증 통과 여부 | `approval_id` 없으면 R1~R4 미수행, EAG 없으면 실행 불가 |

**적용 사례**:

```
Caddy + POST /rpu/issue 호출
→ ACCESS: ✅ (WRITE 권한 Bearer Token 보유)
→ AUTHORITY: ✅ (Caddy = Execution 역할)
→ APPROVAL: approval_id 없으면 R1~R4 건너뜀
             approval_id 있으면 R1~R4 전항목 통과 필요
             EAG 없는 Tier1 write_file → DENY
```

---

### 12-3. Tier별 Approval 요건

| 작업 유형 | ACCESS | AUTHORITY | APPROVAL 요건 |
|---|---|---|---|
| MCP READ (Observation) | Caddy/Domi/Jeni | READ role | Purpose allowlist 준수 |
| Tier2 Write (sandbox/tmp) | Caddy only | Execution role | 불필요 |
| Tier1 Write (canonical) | Caddy only | Execution role | `approval_id` + EAG 필수 |
| RPU 발행 (approval_id 없음) | Caddy/System | Execution role | 5-Step 완료 (R1~R4 skip) |
| RPU 발행 (approval_id 있음) | Caddy/System | Execution role | R1~R4 + 5-Step 전항목 |
| Write Plane 상태 변경 | Beo (loopback) | 비오님 전용 | loopback + body 직접 전달 |
| Observation Fail-Closed 해제 | Beo (loopback) | 비오님 전용 | 6조건 전항목 필수 |

---

## 13. Known Infrastructure Gaps

아래 3건은 API Specification 범위 외 항목입니다. Deployment/Runtime 관측 태스크로 분리 관리합니다.

| ID | 항목 | 분류 | 설명 |
|---|---|---|---|
| INFRA-01 | nginx TLS 매핑 | Deployment | MCP Bridge / Status Server nginx TLS 설정. `/etc/nginx/sites-enabled/` 경로 — ARSS MCP whitelist 外 접근 불가. |
| INFRA-02 | MCP Bridge 외부 URL 확정값 | Deployment | `arss-protocol.org/mcp` 추정 — nginx 설정 직접 확인 전 미확정. |
| INFRA-03 | ARSS Generator 실행 여부 | Runtime | `arss_generator_v1.py` systemd service 파일 없음. 현재 프로세스 활성 여부 미관측. LEGACY 서버로 판정되어 API 명세에는 영향 없음. |

> 이 항목들은 API 명세(Endpoint/Method/Schema/Auth/State Model/Permission Boundary)에 해당하지 않습니다.  
> 비오님 판단에 따라 별도 인프라 관측 태스크로 등록하거나 생략할 수 있습니다.

---

## 부록 A — 관측 이력

| 항목 | v0.1 | v0.2 | v1.0 |
|---|---|---|---|
| Status Server 14 endpoints | ✅ | ✅ | ✅ |
| MCP Write Server 3 endpoints | ✅ | ✅ Tier2 경로 보완 | ✅ |
| MCP HTTP Bridge 13 tools | ✅ | ✅ | ✅ |
| Observation Server 7 endpoints | ❌ | ✅ 전체 확인 | ✅ |
| ARSS Generator (legacy 판정) | ❌ | ✅ | ✅ |
| nginx 라우팅 | ❌ | 부분 확인 | → INFRA-01/02 분리 |

---

*AIBA_API_SPEC_S167_v1.1.md — Caddy S167*
