# Design Contract — DEP-S246-G2-BIDIR-001
## 양방향 AutoRouter (제니→도미 역방향 라우팅)
생성: S246 / 실측 기반 / 추론 금지

---

## 1. 구현 목표

**무엇을 구현하는가:**  
제니 TRUST_NOT_READY 판정 시 n8n이 자동으로 도미 재설계를 요청하고,  
도미 재설계 결과로 제니 2차 검증까지 완료하는 단방향 선형 워크플로우.  
비오님이 TRUST_NOT_READY 교정을 직접 중개하지 않아도 된다.

**무엇을 구현하지 않는가:**  
- 순환 루프 (n8n DAG 제약으로 불가)
- n8n 내부 WORM 기록 (executeCommand Python 실행 불가 판정)
- 기존 WF LzApNQOOl6hqGtOM 수정 (신규 WF 분리)

---

## 2. 실측 엔드포인트 (변경 금지)

| 대상 | 실측값 |
|------|--------|
| 제니 | `POST http://127.0.0.1:8447/ask` |
| 도미 | `POST http://127.0.0.1:8448/ask` |
| 기존 webhook | `POST /webhook/DEP-G2-002-AutoRouter` |
| **신규 webhook** | `POST /webhook/DEP-G2-003-BidirRouter` |
| timeout | **30000ms** (각 httpRequest 동일) |

---

## 3. 실측 요청/응답 구조 (변경 금지)

### 3-A. 캐디 → n8n webhook body
```json
{ "prompt": "<string>", "context": "<string>", "session_id": "<string>" }
```

### 3-B. n8n → 제니/도미 httpRequest body
기존 WF 실측 파라미터 기반:
```javascript
{ prompt: $json.body.prompt, context: $json.body.context || "" }
```
(n8n expression 형식: `={{ JSON.stringify({ prompt: $json.body.prompt, context: $json.body.context || "" }) }}`)

### 3-C. 제니/도미 응답 구조 (HTTP 200, JSON)
```json
{
  "ok": true,
  "text": "<string — TRUST 판정 포함>",
  "error": null,
  "rounds_used": 1,
  "audit": { ... }
}
```

### 3-D. TRUST 판단 조건 (실측)
- `text` 필드에 `"TRUST_NOT_READY"` 포함 → 재설계 필요
- `text` 필드에 `"TRUST_NOT_READY"` 미포함 + `"TRUST_READY"` 포함 → 통과
- n8n if 노드 조건식: `{{ $json.text.includes("TRUST_NOT_READY") }}`

---

## 4. 신규 WF 노드 구성 스펙 (선형 2단계)

```
[1] Receive_Input          webhook
[2] Send_to_Jeni_1         httpRequest → 8447/ask
[3] Check_Trust_1          if  (조건: text includes TRUST_NOT_READY)
    ├─ true(재설계 필요)
    │   [4] Send_to_Domi       httpRequest → 8448/ask
    │   [5] Send_to_Jeni_2     httpRequest → 8447/ask
    │   [6] Respond_redesigned respondToWebhook
    └─ false(통과)
        [7] Respond_ok          respondToWebhook
```

### 노드별 파라미터 요구사항

**[1] Receive_Input**
- type: `n8n-nodes-base.webhook`
- path: `DEP-G2-003-BidirRouter`
- httpMethod: `POST`

**[2] Send_to_Jeni_1**
- type: `n8n-nodes-base.httpRequest`
- url: `http://127.0.0.1:8447/ask`
- method: POST
- contentType: json
- jsonBody: `={{ JSON.stringify({ prompt: $json.body.prompt, context: $json.body.context || "" }) }}`
- timeout: 30000

**[3] Check_Trust_1**
- type: `n8n-nodes-base.if`
- 조건: `{{ $json.text.includes("TRUST_NOT_READY") }}` == true

**[4] Send_to_Domi** (TRUST_NOT_READY 분기)
- type: `n8n-nodes-base.httpRequest`
- url: `http://127.0.0.1:8448/ask`
- method: POST
- contentType: json
- jsonBody: prompt에 [JENI_FEEDBACK] + Jeni_1 응답 text + 원본 prompt 포함
  (n8n expression으로 $('Send_to_Jeni_1') 참조)
- timeout: 30000

**[5] Send_to_Jeni_2** (재검증)
- type: `n8n-nodes-base.httpRequest`
- url: `http://127.0.0.1:8447/ask`
- method: POST
- contentType: json
- jsonBody: prompt에 도미 재설계 text, context 원본 유지
- timeout: 30000

**[6] Respond_redesigned**
- type: `n8n-nodes-base.respondToWebhook`
- respondWith: json
- body: `{ ok: !$json.text.includes("TRUST_NOT_READY"), text: $json.text, stage: "jeni2", redesigned: true }`

**[7] Respond_ok**
- type: `n8n-nodes-base.respondToWebhook`
- respondWith: json
- body: `{ ok: true, text: $('Send_to_Jeni_1').item.json.text, stage: "jeni1", redesigned: false }`

---

## 5. WORM 기록 방식

- **n8n 내부 WORM 기록: 불가** (executeCommand Python 실행 불확실)
- **캐디 측 처리**: autoroute_caller.py 신규 WF URL 대응 확장
  - 신규 WF 응답의 `stage` 필드로 라우팅 경로 판단
  - 기존 `append_auto_route.py` 재사용

---

## 6. 가드 조건 (기존 유지)

| 가드 | 조건 | 값 |
|------|------|----|
| B-3 | 세션당 최대 호출 | 3회 |
| B-2 | error 누적 → deactivate | 2회 |
| timeout | 각 httpRequest | 30000ms |
| 카운터 경로 | `tools/autoroute/runtime/autoroute_counter_S{n}.json` | |

---

## 7. 계약 준수 규칙

이 계약에 명시되지 않은 URL, 경로, 파라미터, 조건식은 설계에 포함 금지.
실측값 변경 금지. 노드 타입은 `n8n-nodes-base.*` 실제 타입만 사용.
