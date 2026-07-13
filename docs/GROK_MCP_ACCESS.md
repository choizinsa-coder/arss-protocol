# Grok MCP 접속 정보 (S408 구축)

## SuperAssistant에 입력할 서버 주소

https://arss-protocol.org/grok/mcp?token=WnZ9CxVWf1Blo59wg_4dvBIRujR8j5poN0F-OsPHDkE

## 보관 위치
- 토큰 원본: /etc/arss/grok_token.txt
- nginx 설정: /etc/nginx/sites-enabled/arss-mcp (location = /grok/mcp)
- 백업: /etc/nginx/sites-available/arss-mcp.bak_s408

## 동작 방식
Grok(SuperAssistant) -> nginx(토큰 검증) -> ARSS 브리지 /mcp -> 파일 읽기

## 검증 상태 (S408)
- 토큰 없음 -> 403 차단
- 잘못된 토큰 -> 403 차단
- 올바른 토큰 POST initialize -> 200 정상
- 올바른 토큰 GET SSE -> 200 heartbeat 정상
- pytest 2332 passed / 0 failed
- commit 1b13e94

## 토큰 재발급이 필요해지면
cat /etc/arss/grok_token.txt 로 현재 토큰 확인 가능.
캐디가 언제든 재발급할 수 있음 (nginx 설정 + 토큰파일 동시 갱신).
