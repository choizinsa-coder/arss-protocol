# Incident RCA Report

- Generated: 2026-06-25T07:48:42.866741+00:00
- Source: /opt/arss/engine/arss-protocol/tools/caddy_error_log/caddy_errors.jsonl
- Total Incidents: 22
- Sessions Covered: 10
- Incident Density: 2.2 /session

## Category Summary

- RC-2: 8
- RC-4: 4
- RC-5: 3
- RC-3: 3
- RC-1: 2
- RC-6: 2

## Per-Category Root Cause

### RC-5 (3)
- Top Root Cause: 에스컬레이션 상황에서 a/b/c 옵션 제시 — 비오님 강력 질책.
- Top Resolution: 
- Sessions: S272, S273, S278

### RC-1 (2)
- Top Root Cause: git commit 전 git status 미확인으로 손상 ssot 커밋. 캐디 과실 확정.
- Top Resolution: 
- Sessions: S272, S282

### RC-2 (8)
- Top Root Cause: find + git ls-files 합성 명령에서 cd 누락.
- Top Resolution: 
- Sessions: S272, S273, S274, S278, S279, S281

### RC-4 (4)
- Top Root Cause: tar 재배포 후 git add 미스테리 미해소로 세션 연장. s273 이월.
- Top Resolution: 
- Sessions: S272, S278, S279

### RC-6 (2)
- Top Root Cause: 설계 토론이 길어져 session close 준비가 세션 말미에 집중됨. 비오님께 대기 부담 유발.
- Top Resolution: 
- Sessions: S275, S284

### RC-3 (3)
- Top Root Cause: 외부 제니 vps 접근 거짓 보고 다수 세션 낙비 — /observe를 '비오님 경험 기준 충족'으로 웩보고. 실제 외부 제니 접근과 다른 구조임.
- Top Resolution: 
- Sessions: S281, S283, S284

## RCA Quality Score

- Score: 65.0 / 100
- rca_coverage: 1.0
- resolution_coverage: 0.0
- category_consistency: 1.0
- structural_recurrence_rate: 0.0
- proposal_completeness: 0.0
- incident_density: 2.2

### Human Review Required
- [ ] A. category 지정이 적절한가
- [ ] B. root_cause가 진짜 원인인가 (증상만 기록했는가)
- [ ] C. resolution이 실제 재발 방지인가 (단순 수정인가)
- [ ] D. guard proposal이 과잉 규칙인가 적절한 예방인가
- [ ] E. 새로운 RC category가 필요한가
