# Logic Density Check — 개념 설계
**문서 ID:** LOGIC-DENSITY-CHECK-v0.1
**설계 기반:** Complexity Governance Direction v1.1 (도미 S105) / 제니 보완 의견
**상태:** EAG-1_LOCKED (Advisory 단계 — enforcement 아님)
**작성일:** 2026-05-09 KST

---

## 1. 목적

CC(Cyclomatic Complexity) 수치는 분기 구조만 측정한다.
따라서 다음 상황에서 CC는 낮지만 실질 복잡도는 높다:

- 깊은 위임 연쇄 (delegation chain)
- 의미 없는 함수 분할 (split-only refactor)
- 로직을 은닉하는 함수 구조

**Logic Density Check의 목적:** "표면 수치"와 "실질 복잡도" 괴리 탐지.

---

## 2. 감지 항목 정의

### LDC-1. LOC 대비 비정상 저복잡도

| 항목 | 정의 |
|---|---|
| **감지 조건** | 함수 LOC ≥ 30 AND CC ≤ 2 |
| **위험 패턴** | 긴 함수지만 분기가 거의 없음 → 순차 실행 로직 은닉 또는 단순 위임 의심 |
| **판정 기준** | Advisory — 제니 수동 검토 |

### LDC-2. Excessive Delegation Chain

| 항목 | 정의 |
|---|---|
| **감지 조건** | 함수 본문이 단일 함수 호출만 3단계 이상 연속 |
| **위험 패턴** | `a() → b() → c() → d()` 구조에서 각 함수가 로직 없이 위임만 수행 |
| **판정 기준** | Advisory — 코드 리뷰 권고 |

### LDC-3. Micro-function Fragmentation

| 항목 | 정의 |
|---|---|
| **감지 조건** | 파일 내 함수 수 ≥ 30 AND Avg CC per File ≤ 2.0 |
| **위험 패턴** | 함수 수는 많지만 각 함수가 지나치게 단순 → split-only refactor 의심 |
| **판정 기준** | Advisory — Shadow Complexity 측정과 연계 |

### LDC-4. Split-only Refactor Pattern

| 항목 | 정의 |
|---|---|
| **감지 조건** | 동일 커밋에서 함수 수 증가 + 전체 LOC 변화 없음 + CC 감소 |
| **위험 패턴** | 실질 로직 이동 없이 CC 수치만 낮추는 분할 |
| **판정 기준** | Advisory — 제니 TRUST_READY 체크 항목 추가 |

---

## 3. 현재 단계 — Advisory Only

| 항목 | 현재 상태 |
|---|---|
| 자동 STOP | **미적용** |
| 측정 주체 | 캐디 (radon + 수동 분석) |
| 검토 주체 | 제니 TRUST_READY 체크리스트 항목 |
| enforcement 전환 | Phase 3 완료 후 별도 EAG |

---

## 4. 제니 TRUST_READY 체크리스트 추가 항목 (Advisory)

제니는 TRUST_READY 검토 시 다음 항목을 수동으로 확인한다:

| 체크 | 내용 |
|---|---|
| LDC-CHK-1 | 신규 함수 중 LOC ≥ 30 AND CC ≤ 2 존재 여부 |
| LDC-CHK-2 | 단순 위임 연쇄 3단계 이상 함수 존재 여부 |
| LDC-CHK-3 | 동일 커밋 내 함수 수 급증 + LOC 동일 패턴 여부 |

> **판정:** PASS / ADVISORY_NOTE 중 하나. Advisory 단계에서 FAIL 발동 없음.

---

## 5. 향후 enforcement 전환 조건

Logic Density Check의 enforcement 전환은 다음 조건 충족 시 도미 설계 의뢰:

1. Phase 3 완료
2. Advisory 단계에서 실제 패턴 3건 이상 탐지 이력 확보
3. 비오 별도 EAG 승인

---

*Logic Density Check v0.1 | EAG-1 LOCKED S105 | Advisory Only | 2026-05-09 KST*
