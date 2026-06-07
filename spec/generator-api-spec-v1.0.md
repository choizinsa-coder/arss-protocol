# Generator API Specification v1.0

> **문서 기준:** `arss_generator_v1.py` v1.0.0 (ACTIVE)
> **최종 갱신:** S204

| 항목 | 값 |
|---|---|
| **문서명** | Generator API Specification |
| **버전** | 1.0 |
| **대상 구현** | `arss_generator_v1.py` |
| **포트** | `8001` (기본값, `GENERATOR_PORT` 환경변수로 변경 가능) |
| **바인딩** | `127.0.0.1` (로컬 전용 — 외부 직접 노출 불가) |
| **EAG 근거** | EAG-1 (2026-04-06), EAG-2 (2026-04-06) |

---

## 0. 책임 범위

Generator는 **RPU 생성 + Verifier 검증**만 담당한다.

| 책임 | 담당 |
|---|---|
| RPU 후보 객체 생성 (해싱 포함) | **Generator (이 문서 범위)** |
| Verifier PASS 확인 | **Generator (이 문서 범위)** |
| `persistence_allowed` 플래그 반환 | **Generator (이 문서 범위)** |
| 파일 저장 (`proof/` 등 실제 저장) | ❌ 상위 실행 계층 책임 |
| GitHub push | ❌ 상위 실행 계층 책임 (Phase 2-B 이후) |
| single-writer 보장 | ❌ 상위 오케스트레이션 책임 |

> **핵심 원칙:** Generator가 `persistence_allowed: true`를 반환해도 파일 저장은 일어나지 않는다.
> 저장 여부는 상위 레이어가 결정한다.

---

## 1. 엔드포인트 목록

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/generate` | RPU 생성 + 검증 |
| `GET` | `/health` | 여스체크 |

---

## 2. POST /generate

### 2.1 인증

| 헤더 | 필수 | 값 |
|---|---|---|
| `Authorization` | **Yes** | `Bearer {AIBA_TOKEN_CADDY}` |
| `Content-Type` | **Yes** | `application/json` |
| `Content-Length` | **Yes** | 바디 바이트 수 |

토큰 불일치 또는 누락 시 → `401 Unauthorized`

---

### 2.2 요청 바디 (JSON)

| 필드 | 타입 | 필수 | 검증 규칙 |
|---|---|---|---|
| `event_type` | String | **Yes** | 비어있지 않은 문자열. `INTERPRETATION_RULE` 허용 목록에 포함되어야 함 |
| `content` | String | **Yes** | 비어있지 않은 문자열 |
| `prev_chain_hash` | String | **Yes** | 소문자 16진수 정확히 64자. 최초 이벤트는 genesis hash(`"000...0"` 64자리) 사용 |
| `actor_id` | String | **Yes** | 키 존재 필수. **빈 문자열 허용** (WF-05 자동화 시나리오) |

#### 요청 예시

```json
{
  "event_type": "AI_OUTPUT_GENERATED",
  "content": "법률 초안 v1 생성 완료",
  "prev_chain_hash": "3b7ac208df6b289db815255dc13c463099d3a9e1d19e9c33e68ddac2aea82fd0",
  "actor_id": "caddy"
}
```

---

### 2.3 응답 — 성공 (200 OK)

```json
{
  "status": "PASS",
  "candidate_rpu": {
    "schema_version": "ARSS-RPU-1.0",
    "rpu_id": "019612ab-cdef-7abc-8def-0123456789ab",
    "timestamp": "2026-06-08T00:30:00.123456Z",
    "actor_id": "caddy",
    "payload": {
      "event_type": "AI_OUTPUT_GENERATED",
      "content": "법률 초안 v1 생성 완료"
    },
    "chain": {
      "payload_hash": "e3b0c44298fc1c149afb....",
      "prev_chain_hash": "3b7ac208df6b289db815...",
      "chain_hash": "a591a6d40bf420404a01..."
    },
    "governance_context": {
      "authority_root": "Beo",
      "jurisdiction": "AIBA_GLOBAL",
      "policy_id": "ARSS_HUB_PROTOCOL_v1.2"
    }
  },
  "persistence_allowed": true
}
```

| 필드 | 설명 |
|---|---|
| `status` | 항상 `"PASS"` (Verifier 통과 시) |
| `candidate_rpu` | 생성된 RPU 객체 (아직 저장되지 않음) |
| `candidate_rpu.rpu_id` | UUIDv7 (시간 정렬 가능) |
| `candidate_rpu.timestamp` | UTC RFC3339 마이크로초 정밀도 |
| `candidate_rpu.payload` | `event_type` + `content` 만 포함 |
| `candidate_rpu.chain.payload_hash` | `SHA256(canonical_json(payload))` |
| `candidate_rpu.chain.chain_hash` | `SHA256((prev_chain_hash + ":" + payload_hash).encode("utf-8"))` |
| `candidate_rpu.governance_context` | 고정값 (ARSS_HUB_PROTOCOL_v1.2) |
| `persistence_allowed` | 항상 `true` (PASS 응답 시). **저장 실행은 상위 레이어 책임** |

---

### 2.4 해시 계산 알고리즘

```
canonical_json(obj)  = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
payload_hash         = SHA256( canonical_json(payload).encode("utf-8") )
chain_hash           = SHA256( (prev_chain_hash + ":" + payload_hash).encode("utf-8") )
```

> ⚠️ **주의:** 이 알고리즘은 IMMUTABLE (LESSON-005). EAG 없이 변경 불가.
> `spec/ARSS-RPU-Spec-v0.1.md`의 JCS(RFC 8785) 기반 스펙과 구현 간 차이 있음
> (현재 구현은 `json.dumps sort_keys` 방식 — Phase 2-B 이후 정합성 검토 예정)

---

### 2.5 오류 응답

| HTTP 코드 | 오류 유형 | 주요 원인 |
|---|---|---|
| `400` | `ValidationError` | 필수 필드 누락, 빈 문자열, `prev_chain_hash` 형식 오류, `event_type` 미허용 |
| `401` | `Unauthorized` | Authorization 헤더 누락 또는 토큰 불일치 |
| `404` | Not found | `/generate` 이외 경로 POST |
| `422` | `VerificationError` | Verifier(`vps_verifier_bridge.py`)가 후보 RPU 거부 |
| `500` | `InternalError` | INTERPRETATION_RULE 로딩 실패 등 내부 오류 |

#### 오류 응답 예시 (400)

```json
{
  "error": "ValidationError",
  "detail": "Missing field: prev_chain_hash"
}
```

#### 오류 응답 예시 (400 — event_type 미허용)

```json
{
  "error": "ValidationError",
  "detail": "ERR-005: event_type 'UNKNOWN_TYPE' not in INTERPRETATION_RULE. Allowed: ['AI_OUTPUT_GENERATED', 'HUMAN_APPROVAL_RECORDED', 'HUMAN_REVIEW_LOGGED']"
}
```

---

## 3. GET /health

인증 불필요.

**응답 (200 OK):**

```json
{
  "status": "ok",
  "version": "arss_generator_v1"
}
```

---

## 4. 내부 처리 흐름

```
POST /generate
    │
    ├─ [1] Authorization 검증
    │       실패 → 401
    │
    ├─ [2] 요청 바디 파싱 (JSON)
    │
    ├─ [3] 입력 검증 (validate_request)
    │       │ event_type, content, prev_chain_hash 비어있는지 확인
    │       │ actor_id 키 존재 여부 확인 (빈 문자열 허용)
    │       │ prev_chain_hash: 64자 소문자 hex 형식 확인
    │       └─ event_type: INTERPRETATION_RULE 허용 목록 대조
    │           실패 → 400
    │
    ├─ [4] RPU 후보 생성 (build_rpu)
    │       payload 구성 → payload_hash → chain_hash → rpu_id(UUIDv7) → timestamp
    │
    ├─ [5] Verifier 연동 (verify_candidate_rpu)
    │       subprocess: vps_verifier_bridge.py --single {tmpfile}
    │       실패 → 422
    │
    └─ [6] 응답 반환
            { status: "PASS", candidate_rpu: {...}, persistence_allowed: true }
```

---

## 5. INTERPRETATION_RULE 의존성

- 기동 시 1회 `INTERPRETATION_RULE_PATH` 파일을 로딩하여 허용 `event_type` 목록 캐싱
- 기본 경로: `/opt/arss/engine/arss-protocol/INTERPRETATION_RULE.json`
- 환경변수 `INTERPRETATION_RULE_PATH`로 오버라이드 가능
- **INTERPRETATION_RULE 변경 시 Generator 재기동 필요** (런타임 갱신 미지원)
- 우선순위: `score_rules_v2_1` → `score_rules_v1` → `score_rules` (fallback)

---

## 6. persist 미지원 항목 (명시)

이 API는 다음을 **지원하지 않는다:**

| 미지원 항목 | 비고 |
|---|---|
| RPU 파일 저장 (`proof/` 등) | 상위 실행 계층 책임 (EAG-1 조건) |
| GitHub push | Phase 2-B 설계 이후 |
| single-writer 보장 | 상위 오케스트레이션 책임 |
| `persist` 요청 파라미터 | 미구현. 요청에 포함해도 무시됨 |
| 배치(Batch) RPU 생성 | 단건(single) 전용 |
| 체인 상태 조회 (`GET /chain`) | 미구현 |

---

## 7. 관련 문서

| 문서 | 설명 |
|---|---|
| `spec/ARSS-RPU-Spec-v0.1.md` | RPU 구조·해시 알고리즘 공식 스펙 |
| `arss_generator_v1.py` | 이 문서의 대상 구현체 |
| `scripts/vps_verifier_bridge.py` | Verifier 연동 브릿지 |
| `INTERPRETATION_RULE.json` | 허용 event_type 목록 |

---

*Generator API Specification v1.0 — AIBA Global Project / S204*
