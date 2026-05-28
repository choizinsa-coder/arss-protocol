# AIBA Session Boot Contract — S144 확정

생성일: 2026-05-23
세션: S144
상태: CONFIRMED
생성자: Caddy / 비오님 확정

---

## 목적

세션 분리 협업(Session-Separated Collaboration)이 실제로 동작하려면
각 에이전트 세션이 시작할 때 무엇을 읽어야 하는지 명확한 계약이 필요하다.

이 문서가 그 계약이다.

---

## 공통 필수 읽기 (모든 에이전트)

모든 세션은 시작 시 다음을 반드시 읽는다:

1. `/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json`
2. `/opt/arss/engine/arss-protocol/tools/sandbox/common/current_task_ticket.json`

current_task_ticket.json이 없거나 stale_lock=true이면:
→ REPORT & WAIT (비오님에게 보고 후 대기)

---

## CADDY Session Boot

### 필수 읽기 (우선순위 순)
1. SESSION_CONTEXT.json
2. common/current_task_ticket.json
3. (current_stage == caddy_impl인 경우) domi/active/proposals/latest
4. (current_stage == caddy_impl인 경우) jeni/active/audit/latest

### 확인 사항
- ticket status == IN_PROGRESS 인지
- assigned_to == caddy 인지
- stale_lock == false 인지
- jeni PASS 확인 (caddy_impl 단계인 경우)

### Boot 실패 조건
- SESSION_CONTEXT.json 없음 → HARD STOP
- ticket 없음 → REPORT & WAIT
- stale_lock=true → REPORT & WAIT (재측정 요구)
- jeni PASS 없는데 caddy_impl 진입 시도 → HARD STOP

---

## DOMI Session Boot

### 필수 읽기 (우선순위 순)
1. SESSION_CONTEXT.json
2. common/current_task_ticket.json
3. caddy/active/notes/{ticket의 observation artifact}

### 확인 사항
- current_stage == domi_design 인지
- assigned_to == domi 인지
- caddy observation artifact 존재 및 stale_lock == false

### Boot 실패 조건
- observation artifact 없음 → REPORT & WAIT
- stale_lock=true → REPORT & WAIT (caddy 재측정 요구)

---

## JENI Session Boot

### 필수 읽기 (우선순위 순)
1. SESSION_CONTEXT.json
2. common/current_task_ticket.json
3. domi/active/proposals/{ticket의 design artifact}
4. caddy/active/receipts/{이전 구현 receipt, 존재하는 경우}

### 확인 사항
- current_stage == jeni_audit 인지
- assigned_to == jeni 인지
- domi design artifact 존재 확인

### Boot 실패 조건
- domi design artifact 없음 → REPORT & WAIT (domi 설계 요구)

---

## "latest" Artifact 탐색 규칙

artifact_type이 "latest"로 참조될 경우:

```
대상 디렉토리 내 파일 중:
  - 파일명 패턴: {type}_{ticket_id}_{YYYYMMDD}.md
  - ticket_id가 일치하는 파일 중 날짜 기준 최신
  - 없으면 REPORT & WAIT
```

---

## Stale 판단 (Boot 시)

Boot 시 observation artifact 생성 시간 확인:
- 2시간 이내: 정상
- 2~4시간: stale_warning 출력 후 계속 진행
- 4시간 초과: stale_lock → REPORT & WAIT

---

## 비오님 Override

비오님이 명시적으로 "계속 진행" 또는 "stale 무시"를 지시한 경우:
Boot 실패 조건 무시하고 진행 가능.
단, 보고는 필수.
