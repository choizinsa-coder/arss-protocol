# AIBA OAuth Secrets 관리 정책

**문서 버전**: v1.0  
**작성 세션**: S213  
**작성자**: 캐디(Caddy)  
**근거**: S212 INC — AIBA_DOMI/JENI_CLIENT_ID/SECRET 누락으로 인한 OAuth 장애 재발 방지

---

## 1. 관리 대상 환경변수 목록

| 환경변수 키 | 런타임 | 용도 | 비고 |
|------------|--------|------|------|
| `AIBA_JENI_CLIENT_ID` | Jeni | Bridge `/token` OAuth client_id | MCP bridge 등록 필수 |
| `AIBA_JENI_CLIENT_SECRET` | Jeni | Bridge `/token` OAuth client_secret | 재발급 대상 |
| `AIBA_GEMINI_API_KEY` | Jeni | Gemini API 직접 호출 키 | Google AI Studio 관리 |
| `AIBA_DOMI_CLIENT_ID` | Domi | Bridge `/token` OAuth client_id | MCP bridge 등록 필수 |
| `AIBA_DOMI_CLIENT_SECRET` | Domi | Bridge `/token` OAuth client_secret | 재발급 대상 |
| `AIBA_OPENAI_API_KEY` | Domi | OpenAI API 직접 호출 키 | OpenAI 대시보드 관리 |

**저장 경로**: `/etc/aiba/secrets.env`  
**로드 방식**: systemd `EnvironmentFile=/etc/aiba/secrets.env`

---

## 2. secrets.env 표준 형식

```env
# AIBA Secrets — /etc/aiba/secrets.env
# 수정 후 반드시 서비스 재시작 필요

# Gemini API
AIBA_GEMINI_API_KEY=<Google AI Studio API Key>
AIBA_GEMINI_MODEL=gemini-2.0-flash

# OpenAI API
AIBA_OPENAI_API_KEY=<OpenAI API Key>
AIBA_DOMI_MODEL=gpt-4o-mini

# Jeni OAuth (MCP Bridge Client)
AIBA_JENI_CLIENT_ID=<Jeni client_id>
AIBA_JENI_CLIENT_SECRET=<Jeni client_secret>

# Domi OAuth (MCP Bridge Client)
AIBA_DOMI_CLIENT_ID=<Domi client_id>
AIBA_DOMI_CLIENT_SECRET=<Domi client_secret>
```

---

## 3. CLIENT_SECRET 재발급 절차

### 3-1. 재발급이 필요한 경우

- OAuth 인증 실패 (런타임 로그에 `OAUTH_FETCH_FAILED` 또는 `OAUTH_NO_TOKEN` 출력)
- CLIENT_SECRET 노출 의심
- 정기 교체 (권고: 90일)

### 3-2. 재발급 절차 (MCP bridge 기준)

```
[PowerShell] SSH로 VPS 접속
ssh root@159.203.125.1

[VPS] MCP bridge client 목록 확인
cat /opt/arss/engine/arss-protocol/tools/mcp_http_bridge/clients.json

[VPS] 신규 SECRET 생성 (예시)
python3 -c "import secrets; print(secrets.token_hex(32))"

[VPS] secrets.env 업데이트
nano /etc/aiba/secrets.env
# AIBA_JENI_CLIENT_SECRET 또는 AIBA_DOMI_CLIENT_SECRET 값 교체

[VPS] bridge clients.json의 해당 client_secret도 동일하게 업데이트
nano /opt/arss/engine/arss-protocol/tools/mcp_http_bridge/clients.json

[VPS] 서비스 재시작 (순서 중요: bridge 먼저)
systemctl restart aiba-mcp-bridge
systemctl restart aiba-jeni-runtime   # Jeni SECRET 변경 시
systemctl restart aiba-domi-runtime   # Domi SECRET 변경 시

[VPS] 재시작 확인
systemctl status aiba-mcp-bridge aiba-jeni-runtime aiba-domi-runtime
```

### 3-3. 재시작 순서 규칙

**반드시 bridge 먼저 재시작** 후 런타임 재시작.  
런타임이 먼저 재시작되면 bridge가 구 SECRET를 보유한 상태에서 새 런타임이 인증 시도 → 즉시 `OAUTH_FETCH_FAILED`.

---

## 4. GEMINI_API_KEY 재발급 절차

```
[브라우저] https://ai.studio/projects 접속
→ 해당 프로젝트 선택 → API Keys → Create API Key (신규) 또는 기존 키 삭제 후 재생성

[VPS] secrets.env 업데이트
nano /etc/aiba/secrets.env
# AIBA_GEMINI_API_KEY 값 교체

[VPS] Jeni 런타임 재시작
systemctl restart aiba-jeni-runtime

[VPS] 정상 동작 확인
curl -s http://127.0.0.1:8447/health | python3 -m json.tool
# "key_present": true 확인
```

**주의**: Gemini API 크레딧 소진 시 429 RESOURCE_EXHAUSTED 발생.  
키 재발급이 아닌 **크레딧 충전**이 필요한 경우 https://ai.studio/projects → Billing 에서 충전.

---

## 5. OpenAI API Key 재발급 절차

```
[브라우저] https://platform.openai.com/api-keys 접속
→ Create new secret key → 값 복사

[VPS] secrets.env 업데이트
nano /etc/aiba/secrets.env
# AIBA_OPENAI_API_KEY 값 교체

[VPS] Domi 런타임 재시작
systemctl restart aiba-domi-runtime

[VPS] 정상 동작 확인
curl -s http://127.0.0.1:8448/health | python3 -m json.tool
# "key_present": true 확인
```

---

## 6. 장애 진단 체크리스트

런타임 OAuth 장애 발생 시 아래 순서로 진단:

| 순서 | 확인 항목 | 명령 |
|------|----------|------|
| 1 | secrets.env 키 존재 여부 | `grep AIBA_ /etc/aiba/secrets.env` |
| 2 | bridge clients.json SECRET 일치 여부 | `cat .../tools/mcp_http_bridge/clients.json` |
| 3 | bridge 서비스 상태 | `systemctl status aiba-mcp-bridge` |
| 4 | 런타임 서비스 상태 | `systemctl status aiba-jeni-runtime aiba-domi-runtime` |
| 5 | bridge 토큰 엔드포인트 직접 테스트 | `curl -X POST http://127.0.0.1:8443/token -d "grant_type=client_credentials&client_id=...&client_secret=..."` |
| 6 | API Key 유효성 (Gemini) | `curl "https://generativelanguage.googleapis.com/v1beta/models?key=$AIBA_GEMINI_API_KEY"` |

---

## 변경 이력

| 버전 | 세션 | 내용 |
|------|------|------|
| v1.0 | S213 | 최초 작성 — S212 OAuth 장애 재발 방지 |
