# DESIGN_S264_governance_3_6.md
# AIBA Governance 3-6: 비오님 역할 재정의 + 브리핑 품질 코드강제
# EAG: EAG-S264-GOV-3-6-001 | Session: S264 | commit: 35bd91d

## PART 1. 비오님 역할 재정의 선언

### 기본 원칙
- 비오님: 승인 주체 (최종 권한 보유자)
- 캐디: 운영 주체

### 비오님 고유 권한 영역 (EAG 필수)
- 신규 거버넌스 채택 / DEP 승인 / 권한 구조 변경 / 운영원칙 변경
- 예외 승인 / 위험 수용 승인 / 종료 승인
- 전략 방향 결정 (Goal 우선순위·자율성 확대·거버넌스 구조 채택·운영철학)
- 최종 분쟁 해결 (에이전트 합의 불가 상태 종료)

### 캐디 자율 영역 (별도 승인 불필요)
- 운영 판단: 문제 분석·원인 추론·설계 의뢰·검증 의뢰·정보 수집·우선순위 정리
- 실행 판단: 승인된 DEP 수행·코드 수정·테스트·관측·보고
- 운영 조정: 도미/제니 호출·추가 자료 수집·설계안 비교·반론 제기
- loop_rule_s263 규칙 1 강등 집행 (TRUST_NOT_READY → TRUST_ADVISORY): 캐디 자율
- loop_rule_s263 규칙 3 Escalate (3라운드+): EAG 트리거

### 비오님 개입 트리거
- Trigger-A: 권한 경계 충돌 (누가 결정권자인지 합의 불가)
- Trigger-B: 전략 방향 분기 (정합 가능한 방향 둘 이상 존재)
- Trigger-C: Deadlock (자율 운영 절차만으로 결론 불가, 3-5 연계)
- Trigger-D: 예외 승인 필요 (기존 거버넌스 이탈 조치 필요)
- Trigger-E: 위험 수용 필요 (위험 제거 불가, 수용 여부 결정 필요)

### 비오님 비개입 원칙
구현 방법·코드 구조·테스트 방식·단순 버그 수정·운영 절차 수행은 비오님 호출 대상 아님.
> 정답을 묻지 않는다. 방향만 묻는다.

---

## PART 2. 브리핑 품질 코드강제

### 구현 위치
- 신규 파일: tools/governance/briefing_gate.py (v1.0)
- 테스트: tests/test_briefing_gate.py (TC-01~10)
- 기존 delegation_policy.py / deadlock_protocol.py 무변경

### 검증 대상 5항목
[CONTEXT] / [HISTORY] / [GOAL] / [CONSTRAINT] / [REQUEST]

### 정책
- 기본 (call_type='design'): BLOCK — 미충족 시 호출 차단, REPORT_AND_WAIT
- 예외 (call_type='query'): WARN — 단순 질의·관측 요청
- 예외 세분화 기준: 3-7 구현 단계 이월 (loop_rule_s263 규칙 2 준수)

### Deadlock Protocol 연계
```
문제 발생 → Briefing Quality Gate → 도미 → 제니 → Deadlock Protocol → EAG
```
브리핑 품질 게이트가 Deadlock 예방층으로 선행 작동한다.

### 선언 문구
> 브리핑 품질은 정보 제공이 아니라 위임 행위의 일부다.
> [CONTEXT][HISTORY][GOAL][CONSTRAINT][REQUEST] 5항목은 설계 의뢰의 최소 계약이며,
> 누락된 위임은 불완전 위임으로 간주한다.
> 캐디는 ask_domi/ask_jeni 호출 전에 브리핑 품질 게이트를 통과해야 한다.

---

## 구현 결과
- commit: 35bd91d
- pytest: 1676 passed / 0 failed / 94 skipped
- 배포 완료: 2026-06-18
