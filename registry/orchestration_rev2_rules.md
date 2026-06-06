# 오케스트레이션 Rev.2 운영 규칙

**설계 근거**: S196 도미 Rev.3 + 제니 TRUST_READY PASS  
**EAG 승인**: S197 비오(Joshua) EAG-1  
**적용 시점**: S197부터  
**A항목**: 구현 완료 (change_classifier v1.0.0, commit ef60a74)

---

## 불변 원칙

1. EAG 게이트 위치 불변 — 병렬화는 게이트 내부에서만 발생
2. 도미(설계) / 제니(검증) / 캐디(실행) 역할 경계 유지
3. Audit pre/post mandatory — 병렬 실행된 모든 작업은 독립 audit_id 보유
4. Fail-Closed — 불확실하면 REPORT & WAIT, 자율 범위 확장 금지

---

## C-1: 관측 단계 병렬화

독립적인 MCP 도구 호출은 순서 의존성이 없는 경우 동시 호출 가능하다.

**허용 (동시 호출)**:
- 각 호출이 서로의 결과에 의존하지 않는 경우
- 예: `list_dir` + `read_file(경로 사전 확정)` + `get_runtime_snapshot`

**금지 (직렬 유지)**:
- 순서 의존성이 있는 경우 (예: `list_dir` 결과로 `read_file` 경로 결정)
- 이전 호출 결과를 다음 호출 파라미터로 사용하는 경우

**실패 처리**:
- 병렬 호출 실패 시: 실패한 호출만 재시도, 성공 결과는 재사용
- 모든 병렬 호출 완료 후에만 다음 단계 진행

---

## C-2: 도미/제니 병렬 호출 프로토콜

### 현재 (직렬)
```
도미 설계 완료 → 캐디 검토 → 제니 TRUST_READY
```

### Rev.2 (병렬)
```
도미 설계 초안 수신
    ├─ 캐디 IMPLEMENTABLE 검토 (시작)
    └─ 제니 PRE_SCAN_READY 호출 (동시 시작)
              ↓
캐디 검토 완료 시점에서 통합:
    - 설계 변경 없음 → PRE_SCAN_READY 결과를 TRUST_READY로 승격
    - 설계 변경 발생 → 변경 유형에 따라 분기
```

### PRE_SCAN_READY 출력 형식
```
[JENI PRE_SCAN]
PRE_SCAN_READY = PASS | FAIL | PARTIAL
SCAN_SCOPE = "도미 초안 기반 사전 검증"
FINDINGS = [...]
REVALIDATION_TRIGGER = NONE | REQUIRED
NOTE = "캐디 검토 후 설계 변경 시 재검증 필요 가능"
```

**주의**: `PRE_SCAN_READY`는 '잠정(Provisional)' 상태. 최종 `TRUST_READY`와 동일 권위를 갖지 않는다.

### 변경 유형 분류

**REUSE_PRESCAN** (프리스캔 결과 부분 재활용 허용 — 명시적 허용 목록):
- 파라미터 값 변경 (숫자/문자열)
- 버전 문자열 변경
- 로그 메시지 변경
- 경로 문자열 변경

**TRIGGER_REJENI** (제니 재호출 필수 — Safe Default):
- 새 파일 추가
- 허용 명령(whitelist) 변경
- actor 권한 변경
- 타임아웃 변경
- EAG scope 변경
- 기존 함수 내부 로직 변경
- 데이터 구조 변경
- **REUSE_PRESCAN에 명시되지 않은 모든 변경** ← Safe Default

### 충돌 방지 규칙
- `TRIGGER_REJENI`에 해당하는 변경 1건이라도 발생 → PRE_SCAN_READY 전체 폐기 → 제니 완전 재호출
- `REUSE_PRESCAN`에만 해당 → 해당 항목 재활용 + 변경 항목만 추가 검증

---

## C-3: 구현 단계 병렬화

EAG 승인 후 파일 간 의존성이 없는 경우 동시 생성 가능하다.

**운영 규칙**:
- 각 파일은 독립 `audit_id`를 가짐
- 파일 간 의존성이 있는 경우 (모듈 A를 import하는 모듈 B) → A 완료 후 B 시작
- pytest는 반드시 모든 병렬 파일 완료 후 통합 실행
- 1개라도 실패 시 전체 REPORT & WAIT (부분 commit 금지)

---

## C-4: EAG scope 파라미터

비오님이 EAG 승인 시 scope를 명시한다. 미지정 시 기본값 `tight`.

| scope | 캐디 자율 범위 | pytest 실패 시 | max_retry |
|---|---|---|---|
| **tight** | 없음 (현재와 동일) | 즉시 REPORT & WAIT | 0 |
| **normal** | 단순 수정 1회 | 1회 자율 재시도 후 REPORT & WAIT | 1 |
| **broad** | assert 값 변경 자율 루프 | change_classifier 검증 통과 시 재시도 | 5 |

**승인 시 scope 지정 예시**:
```
비오: "승인한다. scope: broad"
비오: "승인한다"  ← scope 미지정 시 tight
```

**broad scope 상세 흐름**:
1. pytest 실패 발생
2. 캐디 수정 수행
3. `git diff` → `change_classifier.classify()` 입력
4. `ALLOW` → 자율 재시도 (retry_count += 1)
5. `TRIGGER_REPORT_WAIT` → 즉시 REPORT & WAIT
6. retry_count > 5 → 즉시 REPORT & WAIT
7. 모든 자율 수정은 `exec_audit_trail.log`에 기록

---

## C-5: session_audit_id 병렬 audit 통합

병렬 exec 묶음을 하나의 `session_audit_id`로 추적한다.

**발행 주체**: bridge (`_handle_exec_scoped`)  
**추적 구조**:
```
session_audit_id: SA-S197-<uuid>
├─ child: audit-exec-001 (파일 A) PRE → POST_OK
├─ child: audit-exec-002 (파일 B) PRE → POST_OK
└─ child: audit-exec-003 (파일 C) PRE → POST_FAIL
                                        ↓
                              session_audit_id = INCOMPLETE
                              → REPORT & WAIT
```

**규칙**:
- `session_audit_id`는 병렬 실행 묶음 단위별 1개 발행
- `session_audit_id` 없이 단일 exec 호출 → backward compatible (단일 audit_id만 사용)
- child audit 전부 POST_OK → `session_audit_id` = COMPLETE
- child audit 1개라도 POST_FAIL → `session_audit_id` = INCOMPLETE → REPORT & WAIT
- audit 기록 실패(pre/post) → Fail-Closed → 해당 작업 즉시 중단
