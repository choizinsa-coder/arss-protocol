# AES (AIBA Evidence Standard) v1.0

**EAG 승인**: EAG-S211-AES-001 (비오(Joshua) S211 승인)  
**설계**: 도미(Domi) Rev.1  
**검증**: 제니(Jeni) TRUST_READY PASS  
**적용 시점**: S211부터  

---

## 1. 목적

AIBA 시스템 내 모든 증거(Evidence)를 동일 스키마로 수집·저장·검증·추적한다.

핵심 원칙:
1. 모든 증거는 AES Record를 가진다.
2. 모든 증거는 EAG 또는 Session과 연결된다.
3. 모든 증거는 무결성 해시를 가진다.
4. 제니는 동일 경로로 독립 검증 가능해야 한다.
5. Ledger / Observation 인터페이스는 변경하지 않는다.

---

## 2. Evidence Type

| Type | 설명 | 예시 |
|------|------|------|
| `WORM_PHYSICAL` | 파일시스템 수준 WORM 증적 | `lsattr_worm_s208.json` |
| `LEDGER_CHAIN` | Append-only 체인 증적 | `state_ledger_caddy.jsonl`, `ledger_manifest.jsonl` |
| `OBSERVATION` | 관측 이벤트 | `observation_log.jsonl`, `observation_alerts.jsonl` |
| `CODE_METRIC` | 정적 분석·품질 측정 | `radon_cc_*.txt`, `coverage.txt` |
| `EAG_ARTIFACT` | EAG 산출물 (설계·검증·보고) | EAG 보고서, Jeni TRUST_READY 결과 |

---

## 3. AES Schema

### AES Record (필수 필드)

```json
{
  "evidence_id": "AES-S211-000001",
  "type": "WORM_PHYSICAL",
  "session": "S211",
  "eag_id": "EAG-S211-AES-001",
  "timestamp": "2026-06-09T12:34:56+09:00",
  "collector": "caddy",
  "payload_ref": "ARSS_HUB/04_EVIDENCE/WORM_PHYSICAL/lsattr_worm_s211.json",
  "integrity_hash": "sha256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "metadata": {}
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `evidence_id` | string | AES 전역 식별자 (`AES-{SESSION}-{6자리 시퀀스}`) |
| `type` | enum | Evidence Type 5종 중 하나 |
| `session` | string | 세션 식별자 (예: `S211`) |
| `eag_id` | string \| null | 연결된 EAG ID. EAG 없는 경우 null (session 필수) |
| `timestamp` | ISO 8601 | UTC+9 기준 생성 시각 |
| `collector` | enum | `system` \| `caddy` \| `jeni` |
| `payload_ref` | string | 실제 증거 파일 경로 (ARSS_ROOT 기준 상대경로) |
| `integrity_hash` | string | `sha256:{hex64}` 형식 |
| `metadata` | object | 타입별 확장 필드 |

---

## 4. Storage Layout

```text
ARSS_HUB/
└── 04_EVIDENCE/
    ├── AES_INDEX/
    │   └── aes_index.jsonl          ← 증거 카탈로그 (append-only, chattr +a)
    │
    ├── WORM_PHYSICAL/
    │   └── lsattr_worm_*.json
    │
    ├── LEDGER_CHAIN/
    │   └── snapshots/
    │
    ├── OBSERVATION/
    │   └── observation_snapshots/
    │
    ├── CODE_METRIC/
    │   └── radon/
    │
    └── EAG_ARTIFACT/
        └── EAG-*/
```

### 기존 파일 호환

기존 파일(`lsattr_worm_*.json`, `SNAPSHOT_LOG/`)은 **이동하지 않는다.**  
AES Record의 `payload_ref`로 참조하는 방식으로 호환성을 유지한다.

---

## 5. AES Index

**경로**: `ARSS_HUB/04_EVIDENCE/AES_INDEX/aes_index.jsonl`

- Append-only (`chattr +a` 적용)
- 제니가 이 파일 하나만 읽으면 전체 증거 목록 확보 가능
- 각 라인: AES Record JSON

### 제니 독립 검증 흐름

```text
aes_index.jsonl 읽기
    ↓
payload_ref 확인
    ↓
read_file(payload_ref)
    ↓
SHA256 재계산
    ↓
integrity_hash 비교 → PASS / FAIL
```

---

## 6. Collector 표준

### Collector 종류

| Collector | 역할 | 수집 대상 |
|-----------|------|---------|
| `system` | 자동 수집 | WORM, Ledger, Observation |
| `caddy` | 수동 등록 | 설계 결과, EAG 보고서 |
| `jeni` | 검증 결과 | Verification report |

### 수집 시점

| 시점 | 필수 수집 Type |
|------|--------------|
| EAG 완료 시 | `WORM_PHYSICAL`, `EAG_ARTIFACT` |
| 세션 종료 시 | `LEDGER_CHAIN`, `OBSERVATION` |
| 품질 측정 완료 시 | `CODE_METRIC` |

### Collector 인터페이스

```python
def register_evidence(
    evidence_type: str,
    session: str,
    eag_id: str | None,
    payload_ref: str,
    collector: str,
    metadata: dict = None,
) -> dict:
    """
    AES Record 생성 및 aes_index.jsonl append.
    payload_ref 파일 존재 확인 필수 (참조 무결성).
    반환: AES Record dict
    """
```

---

## 7. 운영 규칙 (AES-OP-001)

| 규칙 ID | 내용 |
|---------|------|
| AES-OP-001 | 모든 신규 증거는 AES Record를 가진다 |
| AES-OP-002 | 증거 원본 수정 금지 |
| AES-OP-003 | AES Record는 Append-only (`aes_index.jsonl` chattr +a) |
| AES-OP-004 | `eag_id` 없는 증거는 `session` 필수 |
| AES-OP-005 | 제니 검증은 AES Index 기준 |

---

## 변경 이력

| 버전 | 세션 | 내용 |
|------|------|------|
| v1.0 | S211 | 최초 제정 — EAG-S211-AES-001 |
