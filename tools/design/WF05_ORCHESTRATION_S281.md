# WF-05: Caddy-Domi-Jeni Orchestration Loop

**EAG**: EAG-S281-N8N-ORCHESTRATION-001  
**세션**: S281  
**등록일**: 2026-06-23  
**Workflow ID**: ZV05Z7YmQMpKCXfi  
**상태**: inactive (비오님 확인 후 activate 필요)  

---

## 목표

비오님이 트리거만 주면 캐디·도미·제니가 VPS를 공동 두뇌로 삼아 자율 협업하고 결과만 반환.

---

## Webhook

```
POST http://159.203.125.1:5678/webhook/wf05-orchestrate
Content-Type: application/json

{
  "task": "할 일 내용",
  "context": "추가 컨텍스트 (선택)",
  "session": "S281"
}
```

---

## 노드 구성

| 단계 | 노드 | 역할 |
|---|---|---|
| 1 | Beo Trigger | Webhook 수신 |
| 2 | Init Loop | 라운드 카운터 초기화 |
| 3 | ask_domi | localhost:8448/ask 성계 요청 |
| 4 | Domi Parse | 응답 파싱 + 라운드 증가 |
| 5 | ask_jeni | localhost:8447/ask 검증 요청 |
| 6 | Verdict Router | TRUST_READY 판정 |
| 7 | TRUST_READY? | 실행 vs 에스컈레이션 분기 |
| 8 | ask_caddy (Claude API) | Anthropic API 실행 |
| 9 | Escalate to Beo | 최대 라운드 초과 시 반환 |
| 10 | Caddy Result | 완료 응답 조립 |

---

## 종료 조건

- TRUST_READY → 케디 실행 → 결과 반환
- TRUST_NOT_READY 2라운드 연속 → 비오님에게 에스컈레이션 + 중단
- MAX_ROUNDS_EXCEEDED 예외 → n8n 오류로 보고

---

## 활성화 방법

1. n8n UI (http://159.203.125.1:5678) 접속
2. WF-05 워크플로우 화면 열기
3. ANTHROPIC_API_KEY 환경변수 등록 확인
4. Toggle 활성화

## 선결 조건 (activate 전 필확인)

- n8n 환경변수 ANTHROPIC_API_KEY 등록
- 도미 runtime localhost:8448 응답 확인
- 제니 runtime localhost:8447 응답 확인
