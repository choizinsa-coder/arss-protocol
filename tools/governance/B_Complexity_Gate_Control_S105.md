# Complexity Gate Control 설계안
**문서 ID:** COMPLEXITY-GATE-v1.0
**설계 기반:** Complexity Governance Direction v1.1 (도미 S105)
**상태:** EAG-1_LOCKED
**작성일:** 2026-05-09 KST

---

## 1. Measurement Flow

```
[코드 변경 발생]
        ↓
[radon cc 측정 — 변경 파일 대상]
        ↓
[Function-Level 판정]
   CC ≤ 10 → PASS
   CC 11~15 → REVIEW
   CC > 15 → HARD STOP
        ↓ (PASS / REVIEW)
[Shadow Complexity 측정]
   File Total CC / Function Count / Avg CC per File / Density
        ↓
[System-Level 판정]
   Mean CC ≤ 5.0 → PASS
   Mean CC > 5.0 → SYSTEM REVIEW REQUIRED
        ↓ (전체 PASS)
[제니 TRUST_READY 체크 — Logic Density 수동 검토]
        ↓
[EAG 진입 허용]
```

---

## 2. 판정 기준 상세

### 2-1. Function-Level

| 판정 | 조건 | 즉시 조치 | 후속 조치 |
|---|---|---|---|
| PASS | CC ≤ 10 | 없음 | — |
| REVIEW | CC 11~15 | EXCEPTIONAL_DEBT_REGISTRY 등재 | expiration_session 설정 필수 |
| HARD STOP | CC > 15 | 병합 차단 | 도미 리팩토링 설계 의뢰 후 재제출 |

### 2-2. 기존 함수 (변경 시 적용)

| 판정 | 조건 | 조치 |
|---|---|---|
| 관리 대상 | CC ≥ 20 | EXCEPTIONAL_DEBT_REGISTRY 등재 확인 |
| HARD STOP 후보 | CC ≥ 30 | 수정 시 CC 개선 필수. 개선 없는 단순 변경 = 거버넌스 위반 |

### 2-3. System-Level

| 판정 | 조건 | 조치 |
|---|---|---|
| PASS | Mean CC ≤ 5.0 | 없음 |
| SYSTEM REVIEW | Mean CC > 5.0 | 비오 보고 → 도미 원인 분석 의뢰 |

---

## 3. Registry Linkage

| 연계 Registry | 연계 조건 | 연계 방식 |
|---|---|---|
| EXCEPTIONAL_DEBT_REGISTRY | REVIEW 판정 시 강제 / 기존 CC≥20 변경 시 | debt_id 발급 + 등재 |
| APPROVED_DEP_REGISTRY | 복잡도 개선 리팩토링 시 신규 dependency 발생 가능 | 기존 EAG 절차 준용 |

---

## 4. Expiration Policy

| 상태 | 만료 조건 | 만료 후 처리 |
|---|---|---|
| REVIEW | expiration_session 도달 또는 CC 개선 확인 | status → RESOLVED |
| REVIEW (3세션 초과) | 자동 승격 | status → HARD_STOP_CANDIDATE |
| HARD_STOP_CANDIDATE | 추가 1세션 경과 + 미개선 | HARD STOP 발동 |
| RESOLVED | CC ≤ 10 개선 확인 | 등재 항목 CLOSED |

---

## 5. Enforcement Timing

| 시점 | 적용 범위 | Gate 활성 여부 |
|---|---|---|
| S105 ~ Phase 3 완료 전 | 설계 LOCK만 | 비활성 (advisory) |
| Phase 3 완료 후 | 신규 함수 전체 | Function-Level Gate 활성 |
| v1.1 이후 | 전체 파일 | Shadow Complexity + System-Level Gate 활성 |
| Logic Density Check | TBD | advisory → enforcement 전환 시 별도 EAG |

---

## 6. 측정 명령어 표준

### 6-1. 신규 함수 CC 측정 (변경 파일 단위)
```bash
/usr/local/bin/radon cc {file_path} --show-complexity -s
```

### 6-2. 전체 프로젝트 System-Level 측정
```bash
/usr/local/bin/radon cc /opt/arss/engine/arss-protocol \
  --show-complexity --average -s \
  --exclude 'venv/*,99_LEGACY/*' \
  2>/dev/null | grep 'Average complexity'
```

### 6-3. 위험군 추출 (C등급 이상)
```bash
/usr/local/bin/radon cc /opt/arss/engine/arss-protocol \
  -n C --show-complexity -s \
  --exclude 'venv/*,99_LEGACY/*' \
  > /tmp/radon_cc_risk.txt
```

### 6-4. Shadow Complexity 측정 (파일 단위)
```bash
/usr/local/bin/radon cc {file_path} --show-complexity -s \
  | awk 'BEGIN{tc=0;fc=0} /^\s+/{tc+=$NF;fc++} \
  END{printf "Total_CC=%d Function_Count=%d Avg_CC=%.2f\n", tc, fc, (fc>0?tc/fc:0)}'
```

---

*Complexity Gate Control v1.0 | EAG-1 LOCKED S105 | 2026-05-09 KST*
