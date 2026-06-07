"""
patch_bridge_test_v140_s201.py
EAG-S201: mcp_http_bridge.py + test_orchestration_rev2.py 현행화

변경 1: EXEC_MAX_PAYLOAD_BYTES 8192 → 32768
변경 2: _handle_exec_scoped VALID 집합에 write_script, run_script 추가
변경 3: _build_write_tool_entries exec_scoped command enum 동일 추가
변경 4: test_orchestration_rev2.py EXEC_RUNTIME_VERSION 1.3.0 → 1.4.0
"""

import os

BRIDGE_PATH = "/opt/arss/engine/arss-protocol/tools/mcp/mcp_http_bridge.py"
TEST_PATH   = "/opt/arss/engine/arss-protocol/tests/test_orchestration_rev2.py"

# ── Bridge 패치 ───────────────────────────────────────────────────────────────
with open(BRIDGE_PATH, "r", encoding="utf-8") as f:
    bridge = f.read()

# 변경 1: EXEC_MAX_PAYLOAD_BYTES
OLD_PAYLOAD = "EXEC_MAX_PAYLOAD_BYTES = 8192"
NEW_PAYLOAD = "EXEC_MAX_PAYLOAD_BYTES = 32768  # v1.4.0: write_script content 수용"
assert OLD_PAYLOAD in bridge, "[FAIL] 패턴 1(payload bytes) 미발견"
bridge = bridge.replace(OLD_PAYLOAD, NEW_PAYLOAD, 1)
print("변경 1 OK: EXEC_MAX_PAYLOAD_BYTES 8192 → 32768")

# 변경 2: VALID 집합
OLD_VALID = 'VALID = frozenset({"pytest","git_commit","git_status","git_diff","systemctl_restart","git_push"})'
NEW_VALID = 'VALID = frozenset({"pytest","git_commit","git_status","git_diff","systemctl_restart","git_push","write_script","run_script"})'
assert OLD_VALID in bridge, "[FAIL] 패턴 2(VALID) 미발견"
bridge = bridge.replace(OLD_VALID, NEW_VALID, 1)
print("변경 2 OK: VALID에 write_script, run_script 추가")

# 변경 3: tool schema enum
OLD_ENUM = '"enum": ["pytest","git_commit","git_status","git_diff","systemctl_restart","git_push"]}, "params"'
NEW_ENUM = '"enum": ["pytest","git_commit","git_status","git_diff","systemctl_restart","git_push","write_script","run_script"]}, "params"'
assert OLD_ENUM in bridge, "[FAIL] 패턴 3(enum) 미발견"
bridge = bridge.replace(OLD_ENUM, NEW_ENUM, 1)
print("변경 3 OK: tool schema enum 업데이트")

with open(BRIDGE_PATH, "w", encoding="utf-8") as f:
    f.write(bridge)
print(f"Bridge PATCH COMPLETE: {BRIDGE_PATH}")

# ── Test 현행화 ───────────────────────────────────────────────────────────────
with open(TEST_PATH, "r", encoding="utf-8") as f:
    test = f.read()

OLD_TEST_VER = '1.3.0'
NEW_TEST_VER = '1.4.0'
assert OLD_TEST_VER in test, "[FAIL] 패턴 4(test version) 미발견"
test = test.replace(OLD_TEST_VER, NEW_TEST_VER, 1)
print("변경 4 OK: test EXEC_RUNTIME_VERSION 1.3.0 → 1.4.0")

with open(TEST_PATH, "w", encoding="utf-8") as f:
    f.write(test)
print(f"Test PATCH COMPLETE: {TEST_PATH}")

# ── 검증 ──────────────────────────────────────────────────────────────────────
with open(BRIDGE_PATH, "r", encoding="utf-8") as f:
    bv = f.read()
with open(TEST_PATH, "r", encoding="utf-8") as f:
    tv = f.read()

assert "32768" in bv,          "[FAIL] EXEC_MAX_PAYLOAD_BYTES"
assert "write_script" in bv,   "[FAIL] write_script in VALID"
assert "run_script" in bv,     "[FAIL] run_script in VALID"
assert "1.4.0" in tv,          "[FAIL] test version"
assert "8192" not in bv,       "[FAIL] 구 payload size 잔존"

print("검증 PASS: 4개 변경 모두 확인 완료")
