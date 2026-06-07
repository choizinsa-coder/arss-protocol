"""
patch_jeni_test_v420_s201.py
test_jeni_runtime_ivloop.py 현행화 — v4.2.0 429 재시도 반영

변경 1: test_execute_gemini_non503_no_retry → 오류코드 429→400 (non-429/503 케이스로 전환)
변경 2: 신규 테스트 2개 추가
  - test_execute_gemini_429_retry_then_fail  (429 재시도 → 재발 → FAIL_CLOSED)
  - test_execute_gemini_429_retry_success    (429 재시도 → 성공)
"""

PATH = "/opt/arss/engine/arss-protocol/tests/test_jeni_runtime_ivloop.py"

with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

# ── 변경 1: test_execute_gemini_non503_no_retry 현행화 ───────────────────────
OLD_TEST = '''def test_execute_gemini_non503_no_retry(monkeypatch):
    call_count = {"n": 0}
    def mock_urlopen(req, timeout):
        call_count["n"] += 1
        raise urllib.error.HTTPError(url="", code=429, msg="TMR", hdrs={}, fp=None)
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is False
    assert "HTTP_429" in result["error"]
    assert call_count["n"] == 1'''

NEW_TEST = '''def test_execute_gemini_non503_no_retry(monkeypatch):
    """400 등 503/429 외 오류코드는 재시도 없이 즉시 FAIL_CLOSED (v4.2.0 현행화)."""
    call_count = {"n": 0}
    def mock_urlopen(req, timeout):
        call_count["n"] += 1
        raise urllib.error.HTTPError(url="", code=400, msg="BAD_REQUEST", hdrs={}, fp=None)
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is False
    assert "HTTP_400" in result["error"]
    assert call_count["n"] == 1  # 재시도 없음


def test_execute_gemini_429_retry_then_fail(monkeypatch):
    """v4.2.0: 429 발생 시 1회 재시도, 재시도도 429면 FAIL_CLOSED (after_429_retry)."""
    call_count = {"n": 0}
    def mock_urlopen(req, timeout):
        call_count["n"] += 1
        raise urllib.error.HTTPError(url="", code=429, msg="TMR", hdrs={}, fp=None)
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is False
    assert "HTTP_429" in result["error"]
    assert "after_429_retry" in result["error"]
    assert call_count["n"] == 2  # 최초 1회 + 재시도 1회


def test_execute_gemini_429_retry_success(monkeypatch):
    """v4.2.0: 429 발생 후 재시도 성공 케이스."""
    import json as _json
    call_count = {"n": 0}
    def mock_urlopen(req, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise urllib.error.HTTPError(url="", code=429, msg="TMR", hdrs={}, fp=None)
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _json.dumps({
            "candidates": [{"content": {"parts": [{"text": "PASS"}]}, "finishReason": "STOP"}]
        }).encode()
        return mock_resp
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is True
    assert call_count["n"] == 2  # 최초 1회(429) + 재시도 1회(성공)'''

assert OLD_TEST in content, "[FAIL] 기존 테스트 패턴 미발견"
content = content.replace(OLD_TEST, NEW_TEST, 1)
print("변경 1 OK: test_execute_gemini_non503_no_retry 현행화 + 신규 2건 추가")

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print(f"PATCH COMPLETE: {PATH}")

# ── 검증 ──────────────────────────────────────────────────────────────────────
with open(PATH, "r", encoding="utf-8") as f:
    verify = f.read()

assert "HTTP_400" in verify,                        "[FAIL] HTTP_400 검증 실패"
assert "test_execute_gemini_429_retry_then_fail" in verify, "[FAIL] 신규 테스트 1 미발견"
assert "test_execute_gemini_429_retry_success" in verify,   "[FAIL] 신규 테스트 2 미발견"
assert "after_429_retry" in verify,                "[FAIL] after_429_retry 미발견"
assert 'code=429, msg="TMR"' not in verify.split("def test_execute_gemini_non503_no_retry")[1].split("def test_execute_gemini_429")[0], \
    "[FAIL] 기존 테스트에 429 코드 잔존"

print("검증 PASS: 현행화 완료")
