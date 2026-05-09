# AIBA_CODING_STANDARD — Complexity Governance Section
**문서 ID:** CODING_STD-COMPLEXITY-v1.0
**상위 문서:** AIBA_CODING_STANDARD_v1.0-rc1
**설계 기반:** Complexity Governance Direction v1.1 (도미 S105)
**Baseline 기준:** PT-S99-GOV-002 (S105, Mean CC = 3.19)
**상태:** EAG-1_LOCKED
**작성일:** 2026-05-09 KST

---

## 1. 목적

Complexity Governance는 단순 CC 수치 제한 정책이 아니다.
목표는 다음 4가지다:

1. 신규 구조 악화 차단
2. 복잡도 부채 추적 가능화
3. 거버넌스 회피 방지
4. 장기 유지보수성 확보

**"수치만 낮춘 코드"는 허용하지 않는다.**

---

## 2. Complexity Standard

### 2-1. Function-Level CC 기준

| 판정 | CC 범위 | 적용 대상 | 조치 |
|---|---|---|---|
| **PASS** | ≤ 10 | 신규 함수 | 즉시 허용 |
| **REVIEW** | 11 ~ 15 | 신규 함수 | EXCEPTIONAL_DEBT_REGISTRY 강제 등재 |
| **HARD STOP** | > 15 | 신규 함수 | EAG 없이 병합 금지 |
| **관리 대상** | ≥ 20 | 기존 함수 | EXCEPTIONAL_DEBT_REGISTRY 등재 |
| **HARD STOP 후보** | ≥ 30 | 기존 함수 | 수정 시 개선 없는 단순 변경 금지 |

> **주의:** 기존 레거시 부채는 즉시 전면 차단하지 않는다. 신규 악화 방지가 우선 목적이다.

### 2-2. System-Level CC 기준

| 지표 | 목표값 | Baseline | 초과 시 조치 |
|---|---|---|---|
| **전체 평균 CC** | ≤ 5.0 | 3.19 (S105) | SYSTEM REVIEW REQUIRED |

---

## 3. Shadow Complexity Countermeasure

단순 함수 분할을 통한 "수치 세탁" 금지.

### 3-1. 추가 측정 항목

| 항목 | 설명 |
|---|---|
| File Total CC | 파일 내 모든 함수 CC 합산 |
| File Function Count | 파일 내 함수 수 |
| Avg CC per File | File Total CC ÷ File Function Count |
| Complexity Density | File Total CC ÷ File LOC |

### 3-2. 감지 대상 패턴

- 파일당 함수 수 급증 (단기간 내 비정상 증가)
- File Total CC 급증
- 지나친 micro-function fragmentation
- LOC 대비 비정상 저복잡도
- excessive delegation chain
- 의미 없는 wrapper function 증가
- split-only refactor pattern (실질 로직 분리 없는 분할)

---

## 4. REVIEW 처리 규칙 (Time-boxed Lock)

REVIEW는 묵인이 아니다. REVIEW 통과 항목은 반드시 만료되어야 한다.

### 4-1. EXCEPTIONAL_DEBT_REGISTRY 강제 등재 항목

| 필드 | 필수 여부 | 설명 |
|---|---|---|
| `debt_id` | 필수 | 고유 식별자 |
| `function_name` | 필수 | 대상 함수명 |
| `file_path` | 필수 | VPS 경로 |
| `cc_score` | 필수 | 측정 시점 CC 점수 |
| `created_session` | 필수 | 등재 세션 번호 |
| `owner` | 필수 | 책임 에이전트 |
| `debt_reason` | 필수 | 부채 발생 사유 |
| `expiration_session` | 필수 | 만료 세션 (최대 created_session + 3) |
| `status` | 필수 | REVIEW / HARD_STOP_CANDIDATE / RESOLVED |

### 4-2. Time-boxed Lock 규칙

- REVIEW 상태가 **3세션 이상 지속** 시 → 자동 **HARD_STOP_CANDIDATE** 승격
- HARD_STOP_CANDIDATE 상태에서 수정 없이 추가 1세션 경과 → **HARD STOP 발동**
- 세션 카운트 기준: **비오 실제 개설 세션** 기준 (rc1 review_expiry_rule 준용)

---

## 5. Logic Density Check (Advisory 단계)

### 5-1. 목적

"실질 복잡도"와 "표면 수치" 괴리 감지.
CC 수치는 낮지만 실질적으로 복잡한 코드 구조 탐지.

### 5-2. 감지 항목 (초기 advisory — enforcement 아님)

| 항목 | 설명 |
|---|---|
| LOC 대비 비정상 저복잡도 | 함수 LOC가 크지만 CC가 비정상적으로 낮은 경우 |
| Excessive delegation chain | 3단계 이상 단순 위임 연쇄 |
| Readability degradation | 함수명/변수명이 로직을 은닉하는 구조 |
| Split-only refactor | 로직 이동 없이 분할만 발생한 리팩토링 |

> **현재 단계:** advisory only. 자동 STOP 미적용. 제니 TRUST_READY 체크리스트 항목으로 수동 검토.

---

## 6. Governance Principle

| 원칙 | 내용 |
|---|---|
| P-1 | 신규 부채 생성 차단이 최우선 |
| P-2 | 기존 부채는 추적 가능 상태로 관리 |
| P-3 | 예외는 허용 가능하지만 반드시 만료되어야 함 |
| P-4 | 수치 최적화보다 구조 안정성이 우선 |

---

## 7. Enforcement 활성화 일정

| 단계 | 시점 | 내용 |
|---|---|---|
| 현재 (S105~) | Phase 3 진행 중 | 설계 LOCK / enforcement 비활성 |
| Phase 3 완료 후 | TBD | Gate Control 활성화 / 자동 측정 체계 가동 |
| v1.1 이후 | TBD | Logic Density Check enforcement 검토 |

---

*AIBA_CODING_STANDARD Complexity Section v1.0 | EAG-1 LOCKED S105 | 2026-05-09 KST*
