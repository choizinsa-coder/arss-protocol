"""
patch_jeni_runtime_v420_s201.py
EAG-S201: aiba_jeni_runtime.py v4.1.0 → v4.2.0

변경 1: import re 추가
변경 2: RUNTIME_VERSION "4.1.0" → "4.2.0"
변경 3: GEMINI_429_RETRY_MAX_SLEEP 상수 추가
변경 4: _execute_gemini_request — 429 Retry-After 재시도 추가
변경 5: do_POST — HTTP 응답 코드 200 통일 (502 제거)
"""

import re as _re

PATH = "/opt/arss/engine/arss-protocol/tools/jeni_runtime/aiba_jeni_runtime.py"

with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

# ── 변경 1: import re 추가 ────────────────────────────────────────────────────
OLD_IMPORT = "import glob\nimport json\nimport os\nimport sys\nimport time\nimport urllib.request\nimport urllib.error"
NEW_IMPORT = "import glob\nimport json\nimport os\nimport re\nimport sys\nimport time\nimport urllib.request\nimport urllib.error"
assert OLD_IMPORT in content, "[FAIL] 패턴 1(import) 미발견"
content = content.replace(OLD_IMPORT, NEW_IMPORT, 1)
print("변경 1 OK: import re 추가")

# ── 변경 2: 버전 업 ──────────────────────────────────────────────────────────
OLD_VER = 'RUNTIME_VERSION = "4.1.0"'
NEW_VER = 'RUNTIME_VERSION = "4.2.0"'
assert OLD_VER in content, "[FAIL] 패턴 2(version) 미발견"
content = content.replace(OLD_VER, NEW_VER, 1)
print("변경 2 OK: v4.1.0 → v4.2.0")

# ── 변경 3: GEMINI_429_RETRY_MAX_SLEEP 상수 추가 ─────────────────────────────
OLD_SLEEP = "GEMINI_503_RETRY_SLEEP = 2  # 503 재시도 대기 시간(초)"
NEW_SLEEP = (
    "GEMINI_503_RETRY_SLEEP = 2  # 503 재시도 대기 시간(초)\n"
    "GEMINI_429_RETRY_MAX_SLEEP = 60  # 429 Retry-After 상한(초)"
)
assert OLD_SLEEP in content, "[FAIL] 패턴 3(상수) 미발견"
content = content.replace(OLD_SLEEP, NEW_SLEEP, 1)
print("변경 3 OK: GEMINI_429_RETRY_MAX_SLEEP 상수 추가")

# ── 변경 4: _execute_gemini_request — 429 재시도 추가 ────────────────────────
OLD_429 = (
    "        return {\"ok\": False, \"text\": \"\", \"function_calls\": [], \"parts\": [],\n"
    "                \"error\": f\"HTTP_{e.code}: {_read_http_error_body(e)}\"}\n"
    "    except urllib.error.URLError as e:"
)
NEW_429 = (
    "        elif e.code == 429:\n"
    "            # 429 Rate Limit — Retry-After 기반 대기 후 1회 재시도 (S201 EAG)\n"
    "            body_text = _read_http_error_body(e)\n"
    "            match = re.search(r'retry\\s+in\\s+([\\d.]+)\\s*s', body_text, re.IGNORECASE)\n"
    "            retry_delay = float(match.group(1)) if match else 30.0\n"
    "            retry_delay = min(retry_delay, GEMINI_429_RETRY_MAX_SLEEP)\n"
    "            time.sleep(retry_delay)\n"
    "            try:\n"
    "                with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT) as resp3:\n"
    "                    data3 = json.loads(resp3.read().decode(\"utf-8\"))\n"
    "                    parts3 = _extract_parts(data3)\n"
    "                    if not parts3:\n"
    "                        finish3 = _extract_finish_reason(data3)\n"
    "                        return {\"ok\": False, \"text\": \"\", \"function_calls\": [], \"parts\": [],\n"
    "                                \"error\": f\"NO_PARTS: finish_reason={finish3} (after_429_retry)\"}\n"
    "                    return {\"ok\": True, \"text\": _extract_text_from_parts(parts3),\n"
    "                            \"function_calls\": _extract_function_calls(parts3),\n"
    "                            \"parts\": parts3, \"error\": None}\n"
    "            except urllib.error.HTTPError as e3:\n"
    "                return {\"ok\": False, \"text\": \"\", \"function_calls\": [], \"parts\": [],\n"
    "                        \"error\": f\"HTTP_{e3.code}: {_read_http_error_body(e3)} (after_429_retry)\"}\n"
    "            except Exception as e3:\n"
    "                return {\"ok\": False, \"text\": \"\", \"function_calls\": [], \"parts\": [],\n"
    "                        \"error\": f\"FAIL_CLOSED: 429 retry error — {e3}\"}\n"
    "        return {\"ok\": False, \"text\": \"\", \"function_calls\": [], \"parts\": [],\n"
    "                \"error\": f\"HTTP_{e.code}: {_read_http_error_body(e)}\"}\n"
    "    except urllib.error.URLError as e:"
)
assert OLD_429 in content, "[FAIL] 패턴 4(429 재시도) 미발견"
content = content.replace(OLD_429, NEW_429, 1)
print("변경 4 OK: 429 Retry-After 재시도 추가")

# ── 변경 5: do_POST HTTP 200 통일 ─────────────────────────────────────────────
OLD_CODE = "        code = 200 if result[\"ok\"] else 502\n        self._send_json(code, result)"
NEW_CODE = "        self._send_json(200, result)  # v4.2.0: 항상 200, ok=false 시 body에 error 포함"
assert OLD_CODE in content, "[FAIL] 패턴 5(HTTP 200) 미발견"
content = content.replace(OLD_CODE, NEW_CODE, 1)
print("변경 5 OK: HTTP 응답 코드 200 통일")

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print(f"PATCH COMPLETE: {PATH}")

# ── 검증 ──────────────────────────────────────────────────────────────────────
with open(PATH, "r", encoding="utf-8") as f:
    verify = f.read()

assert 'RUNTIME_VERSION = "4.2.0"' in verify,    "[FAIL] 버전 검증 실패"
assert "import re" in verify,                      "[FAIL] import re 검증 실패"
assert "GEMINI_429_RETRY_MAX_SLEEP" in verify,     "[FAIL] 상수 검증 실패"
assert "after_429_retry" in verify,                "[FAIL] 429 재시도 검증 실패"
assert "v4.2.0: 항상 200" in verify,              "[FAIL] HTTP 200 통일 검증 실패"
assert "code = 200 if result" not in verify,       "[FAIL] 구 502 코드 잔존"
assert 'RUNTIME_VERSION = "4.1.0"' not in verify,  "[FAIL] 구 버전 잔존"

print("검증 PASS: 5개 변경 모두 확인 완료")
