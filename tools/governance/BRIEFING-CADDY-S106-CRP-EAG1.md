# BRIEFING-CADDY-S106-CRP-EAG1
# CRP v1.1 패키지 EAG-1 제출
# S106 | 2026-05-09 | 캐디 작성

---

## 1. 요청 개요

| 항목 | 내용 |
|---|---|
| 요청 유형 | EAG-1 승인 요청 |
| 대상 | CRP v1.1 패키지 (설계 산출물 4개) |
| 목적 | exceptional_debt_registry v1.0 schema 및 CRP_HISTORY_LOG schema v1.0 공식 승인 |
| 설계 권한 | 도미 (PASS 판정 완료) |
| 검토 이력 | 도미 CONDITIONAL_PASS → 보완 완료 → 도미 PASS |

---

## 2. EAG-1 승인 범위

### 승인 대상: 설계 산출물 4개

| # | 파일 | 내용 |
|---|---|---|
| 1 | CRP_Master_Plan_v1.1_FINAL_S106.md | CRP 통합 계획 (철학 LOCK / Tier 체계 / Gate 기준 / 로드맵) |
| 2 | CRP_Governance_Supplements_v1.1_FINAL_S106.md | EAG-EMERGENCY Rule / Discharge Lifecycle / Enforced 전환 트리거 |
| 3 | CRP_HISTORY_LOG_schema_v1.0_FINAL_S106.json | 치료 이력 감사 증적 ledger 스키마 |
| 4 | exceptional_debt_registry_schema_v1.0_FINAL_S106.json | 기술 부채 registry v1.0 스키마 |

---

## 3. 승인 시 허용 항목

| 항목 | 상태 |
|---|---|
| CRP 설계 산출물 4개 공식 문서로 인정 | 허용 |
| exceptional_debt_registry v0.1 → v1.0 승격 | 허용 |
| Phase B Remediation Planning 착수 | 허용 (advisory 상태에서 가능) |
| CRP_HISTORY_LOG 구조 확정 선언 | 허용 |
| Advisory → Enforced 전환 조건 추적 시작 | 허용 |

---

## 4. 승인 후에도 금지 유지 항목 (EAG-1만으로 해제 불가)

| 항목 | 이유 |
|---|---|
| enforcement_active = false 유지 | Phase 3 완료 후 별도 EAG 필요 |
| 핵심 함수 리팩토링 금지 (rpu_issue 등) | PT-S81 안정화 이전 surgical refactor 금지 |
| 실제 CRP_HISTORY_LOG record 생성 없음 | EAG 승인 후 최초 실제 기록 시 생성 |
| Phase C Controlled Surgical Refactor 금지 | Enforced 전환 조건 충족 + 별도 EAG 필요 |
| VPS 파일 배포 없음 | EAG-2 승인 후 수행 |

---

## 5. 핵심 설계 결정 요약

### CRP 철학 (IMMUTABLE)
- CRP = 구조 건강 운영 체계 / 기술 부채 lifecycle governance
- 숫자 최적화 / cosmetic refactor / metric gaming = 목적 위반

### exceptional_debt_registry v1.0 주요 변경 (v0.1 대비)
- status enum 8개 확정 (ACTIVE / REVIEW / IN_PROGRESS / ESCALATED / DISCHARGED / EMERGENCY_OVERRIDE / DEFERRED / ARCHIVED)
- expiry_policy 4종 확정 (NONE / SESSION / DATE / CONDITION)
- CRP_HISTORY_LOG linkage 필드 추가 (history_refs / last_history_ref / discharge_history_ref)
- reactivation 정책 추가 (DISCHARGED → ACTIVE 재활성화, 신규 debt_id 발급 금지)
- Jeni verification intensity 필드 추가 (verification_level / jeni_required / jeni_status)

### CRP_HISTORY_LOG v1.0 주요 사항
- 별도 JSON artifact (registry와 분리)
- append-only HARD LOCK (overwrite 금지 / correction은 신규 record)
- records 배열 현재 빈 상태 (EAG 승인 후 최초 실제 기록 시 생성)
- example record는 non-binding sample only

### EAG-EMERGENCY HARD LOCK
- expiration_session 없는 EAG-EMERGENCY = INVALID
- 영구 emergency 상태 금지

### Advisory → Enforced 전환
- 9개 조건 전항목 충족 + 비오 EAG 승인 필요
- Enforced 전환 후 rollback 조건 5개 정의 (irreversible 선언 금지)

---

## 6. 현재 상태

| 항목 | 상태 |
|---|---|
| 도미 설계 | PASS |
| 제니 검증 | 미수행 (EAG-1 승인 후 진행) |
| EAG-1 | **비오님 승인 대기** |
| EAG-2 | EAG-1 이후 |
| VPS 배포 | EAG-2 이후 |
