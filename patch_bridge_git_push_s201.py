"""
patch_bridge_git_push_s201.py
EAG-1-S201: mcp_http_bridge.py exec_scoped VALID 집합 + tool schema에 git_push 추가

변경 1: _handle_exec_scoped VALID 집합
변경 2: _build_write_tool_entries exec_scoped command enum
"""

PATH = "/opt/arss/engine/arss-protocol/tools/mcp/mcp_http_bridge.py"

with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

# ── 변경 1: _handle_exec_scoped VALID 집합 ───────────────────────────────────
OLD_VALID = 'VALID = frozenset({"pytest","git_commit","git_status","git_diff","systemctl_restart"})'
NEW_VALID = 'VALID = frozenset({"pytest","git_commit","git_status","git_diff","systemctl_restart","git_push"})'

assert OLD_VALID in content, f"[FAIL] 패턴 1 미발견 — 중단"
content = content.replace(OLD_VALID, NEW_VALID, 1)
print("변경 1 OK: VALID 집합 git_push 추가")

# ── 변경 2: _build_write_tool_entries exec_scoped command enum ───────────────
OLD_ENUM = '"enum": ["pytest","git_commit","git_status","git_diff","systemctl_restart"]}, "params"'
NEW_ENUM = '"enum": ["pytest","git_commit","git_status","git_diff","systemctl_restart","git_push"]}, "params"'

assert OLD_ENUM in content, f"[FAIL] 패턴 2 미발견 — 중단"
content = content.replace(OLD_ENUM, NEW_ENUM, 1)
print("변경 2 OK: tool schema enum git_push 추가")

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print(f"PATCH COMPLETE: {PATH}")

# ── 검증 ──────────────────────────────────────────────────────────────────────
with open(PATH, "r", encoding="utf-8") as f:
    verify = f.read()

assert NEW_VALID in verify, "[FAIL] VALID 집합 검증 실패"
assert NEW_ENUM in verify, "[FAIL] enum 검증 실패"
assert OLD_VALID not in verify, "[FAIL] 구 VALID 잔존"
assert OLD_ENUM not in verify, "[FAIL] 구 enum 잔존"

print("검증 PASS: 구 패턴 소거, 신 패턴 확인 완료")
