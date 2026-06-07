"""
patch_caddy_sandbox_fix_s201.py
CADDY_SANDBOX 정의 위치 수정 — ARSS_ROOT 이전(버그) → AUDIT_LOG_PATH 이후(수정)
"""

PATH = "/opt/arss/engine/arss-protocol/tools/exec_runtime/aiba_exec_runtime.py"

with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

# 잘못된 위치에서 CADDY_SANDBOX 블록 제거
OLD_WRONG = (
    "# caddy sandbox 경로 (write_script / run_script 전용)\n"
    'CADDY_SANDBOX = os.path.join(ARSS_ROOT, "tools/sandbox/caddy/active")\n'
    "\n"
    "# git_push allowlist (Fail-Closed)\n"
)
NEW_WRONG = "# git_push allowlist (Fail-Closed)\n"
assert OLD_WRONG in content, "[FAIL] 잘못된 위치 CADDY_SANDBOX 미발견"
content = content.replace(OLD_WRONG, NEW_WRONG, 1)
print("단계 1 OK: 잘못된 위치 제거")

# AUDIT_LOG_PATH 이후(ARSS_ROOT 정의 이후)에 삽입
OLD_AUDIT = (
    'AUDIT_LOG_PATH = os.path.join(ARSS_ROOT, "tools/mcp/exec_audit_trail.log")\n'
)
NEW_AUDIT = (
    'AUDIT_LOG_PATH = os.path.join(ARSS_ROOT, "tools/mcp/exec_audit_trail.log")\n'
    "\n"
    "# caddy sandbox 경로 (write_script / run_script 전용, S201 EAG-B 위치 수정)\n"
    'CADDY_SANDBOX = os.path.join(ARSS_ROOT, "tools/sandbox/caddy/active")\n'
)
assert OLD_AUDIT in content, "[FAIL] AUDIT_LOG_PATH 패턴 미발견"
content = content.replace(OLD_AUDIT, NEW_AUDIT, 1)
print("단계 2 OK: ARSS_ROOT 이후 올바른 위치에 삽입")

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

# 검증
with open(PATH, "r", encoding="utf-8") as f:
    verify = f.read()

arss_pos   = verify.index('ARSS_ROOT = "/opt/arss/engine/arss-protocol"')
caddy_pos  = verify.index("CADDY_SANDBOX = os.path.join(ARSS_ROOT")
assert caddy_pos > arss_pos, "[FAIL] CADDY_SANDBOX가 ARSS_ROOT 이전에 있음"
assert "# git_push allowlist" in verify, "[FAIL] git_push allowlist 소실"

print(f"검증 PASS: ARSS_ROOT({arss_pos}) < CADDY_SANDBOX({caddy_pos}) — 순서 정상")
print("PATCH COMPLETE")
