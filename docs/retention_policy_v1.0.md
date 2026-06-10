# AIBA Retention Policy v1.0

**EAG:** EAG-S219-GOV-001
**확정 세션:** S219
**승인자:** 비오(Joshua)
**DEP 체인:** 도미 설계 v2 → 캐디 IMPLEMENTABLE=YES → 제니 TRUST_READY=PASS → 비오 EAG 승인
**task_ref:** PT-S99-GOV-001

---

## 등급 정의 및 수치 LOCK

| 등급 | VPS 보존 | Drive 보존 | 만료 처리 |
|------|----------|------------|----------|
| R3   | 영구      | 영구        | 삭제 없음 |
| R2   | 3년       | 영구        | VPS→Archive Export |
| R1   | 180일     | 3년         | 자동 Archive 후 VPS 삭제 |
| R0   | 0일 (예외: 최대 24h) | 없음 | 자동 삭제 |

---

## 등급별 대상 아티팩트

### R3 — 영구 보존
- WORM ledger (`tools/ledger/`)
- ledger_manifest
- EAG approvals (`evidence/eag_approvals/`)
- session_journal (`session_journal/session_journal.jsonl`)
- SESSION_CONTEXT_S{n}_FINAL.json

### R2 — 장기 보존 (VPS 3년 / Drive 영구)
- SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json
- Decision Log (Phase 2 예정)
- 주요 Incident Reports

### R1 — 운영 보존 (VPS 180일 / Drive 3년)
- Receipts (`evidence/receipts/`)
- PEC failures (`logs/pec_failures/`)
- Daily Session Reports
- Visibility Metrics 원본

### R0 — 비보존 (세션 종료 즉시 파기)
대상:
- 임시 bootstrap 산출물
- 재생성 가능한 migration 중간 결과
- 일회성 검증 로그
- 임시 캐시

R0 지정 조건 (모두 충족 필요):
- 재생성 가능
- 의사결정 근거 아님
- 감사 추적 불필요

예외: 마이그레이션/복구 검증 시 최대 24시간 임시 보존 허용

---

## WORM 특례 규정

적용 대상:
- `ledger/*`
- `session_journal/*`
- `eag_approvals/*`

원칙: 일반 삭제 정책 적용 금지. RETENTION_FROZEN 상태 유지.

아카이브 절차:
```
RETENTION_FROZEN
→ export
→ checksum 생성
→ 비오(Joshua) EAG 승인        ← 필수 게이트
→ cold archive 이동
→ read-only archive 유지
```

비고: cold archive 저장 매체(Drive/NAS/Object Storage)는 별도 구현 설계 필요.

---

## Phase 1 적용

- session_journal: **R3** (Phase 1 Shared Memory 핵심 계층)
- WORM ledger: **R3**
- EAG approvals: **R3**

---

## 제니 TRUST-ADVISORY (운영 주의사항)

1. R0 예외 조항: 자동 파기 타이머 및 캐디 무결성 검증 루틴 연동 여부 실행 단계 모니터링 필요
2. WORM EAG 게이트: 승인 요청 시 전후 체크섬 위변조 여부 시각적 대조 인터페이스 향후 보완 필요
