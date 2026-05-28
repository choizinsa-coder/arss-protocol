# AIBA Sandbox Task Ticket Schema — S144 확정

생성일: 2026-05-23
세션: S144
상태: CONFIRMED
생성자: Caddy / 비오님 확정

---

## 1. 파일 위치

```
/tools/sandbox/common/current_task_ticket.json
```

active ticket은 반드시 1개만 존재 (LOCK-5).

---

## 2. Schema 정의

```json
{
  "schema_version": "1.0",
  "ticket_id": "TKT-{SESSION}-{SEQ:03d}",
  "created_at": "ISO8601+09:00",
  "updated_at": "ISO8601+09:00",
  "task_ref": "PT-SXXX-XXX-001",
  "title": "작업 제목",
  "status": "PENDING | IN_PROGRESS | BLOCKED | DONE | CANCELED",
  "current_stage": "caddy_observation | domi_design | jeni_audit | caddy_impl | beo_review",
  "next_stage": "위와 동일 enum",
  "assigned_to": "caddy | domi | jeni | beo",
  "dispatch_pending": false,
  "dispatch_reason": null,

  "artifacts": {
    "observation": "caddy/active/notes/{filename}",
    "design": "domi/active/proposals/{filename}",
    "audit": "jeni/active/audit/{filename}",
    "receipt": "caddy/active/receipts/{filename}"
  },

  "stale": {
    "observation_created_at": null,
    "observation_stale_warn_at": null,
    "observation_stale_lock_at": null,
    "stale_locked": false
  },

  "governance": {
    "eag_ref": null,
    "beo_approval_at": null,
    "lock_flags": {
      "ticket_integrity": false,
      "stale_lock": false,
      "circuit_breaker": false,
      "single_active_violated": false
    }
  },

  "hash": "SHA256_of_above_fields_excluding_hash"
}
```

---

## 3. Status Enum 설명

| Status | 의미 |
|---|---|
| PENDING | 작업 대기 중, agent 미배정 |
| IN_PROGRESS | 현재 stage 진행 중 |
| BLOCKED | 외부 의존성으로 대기 |
| DONE | 모든 stage 완료 |
| CANCELED | 비오님 결정으로 취소 |

---

## 4. Stage Enum 설명

| Stage | 담당 | 입력 artifact | 출력 artifact |
|---|---|---|---|
| caddy_observation | Caddy | SESSION_CONTEXT + task desc | caddy/active/notes/ |
| domi_design | Domi | caddy observation | domi/active/proposals/ |
| jeni_audit | Jeni | domi proposal + caddy receipt | jeni/active/audit/ |
| caddy_impl | Caddy | domi proposal + jeni PASS | caddy/active/receipts/ |
| beo_review | 비오님 | 모든 artifact | 승인/반려 결정 |

---

## 5. Artifact 파일명 규칙

```
패턴: {artifact_type}_{ticket_id}_{YYYYMMDD}.{ext}

예시:
  caddy/active/notes/observation_TKT-S144-001_20260523.md
  domi/active/proposals/design_TKT-S144-001_20260523.md
  jeni/active/audit/audit_TKT-S144-001_20260523.md
  caddy/active/receipts/receipt_TKT-S144-001_20260523.md
```

---

## 6. Hash 계산 방법

```python
import json, hashlib

def compute_ticket_hash(ticket: dict) -> str:
    body = {k: v for k, v in ticket.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
```

---

## 7. Stale 판단 기준 (LOCK-4)

| 경과 시간 | 상태 |
|---|---|
| 0 ~ 2시간 | 정상 |
| 2 ~ 4시간 | stale_warning (dispatch 허용, 경고만) |
| 4시간 초과 | stale_lock (dispatch 금지, 재측정 요구) |

stale 기준은 observation artifact 기준.
다른 artifact(design, audit, receipt)는 별도 TTL 미적용 (Phase 0).

---

## 8. circuit_breaker 발동 조건 (LOCK-3)

다음 중 하나 발생 시:

- stage 전환 횟수 > 10 (동일 ticket 내)
- dispatch 시도 > 5회 연속 실패
- ticket 생성 후 72시간 초과 (DONE 아님)

발동 시: dispatch_pending = false, circuit_breaker = true
해제: 비오님 직접 승인 필요.

---

## 9. Ticket 생성/수정 권한

| 행위 | 권한 |
|---|---|
| ticket 생성 | Caddy (비오님 지시 후) |
| status 변경 | Caddy (stage 완료 시), 비오님 (언제든) |
| hash 재계산 | 모든 변경 시 필수 |
| ticket 삭제 | 비오님만 가능 |
