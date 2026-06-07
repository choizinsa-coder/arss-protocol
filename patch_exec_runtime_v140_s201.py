"""
patch_exec_runtime_v140_s201.py
EAG-S201: aiba_exec_runtime.py v1.3.0 → v1.4.0

변경 1: EXEC_RUNTIME_VERSION 1.3.0 → 1.4.0
변경 2: CADDY_SANDBOX 상수 추가
변경 3: COMMAND_TIMEOUTS에 write_script, run_script 추가
변경 4: _validate_and_build_cmd에 write_script, run_script 분기 추가
변경 5: _run_command에 write_script, run_script 실행 처리 추가
변경 6: 응답에 write_script/run_script 전용 필드 추가
"""

PATH = "/opt/arss/engine/arss-protocol/tools/exec_runtime/aiba_exec_runtime.py"

with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

# ── 변경 1: 버전 업 ──────────────────────────────────────────────────────────
OLD_VER = 'EXEC_RUNTIME_VERSION = "1.3.0"'
NEW_VER = 'EXEC_RUNTIME_VERSION = "1.4.0"'
assert OLD_VER in content, "[FAIL] 패턴 1(version) 미발견"
content = content.replace(OLD_VER, NEW_VER, 1)
print("변경 1 OK: v1.3.0 → v1.4.0")

# ── 변경 2: CADDY_SANDBOX 상수 추가 ──────────────────────────────────────────
OLD_SANDBOX = '# git_push allowlist (Fail-Closed)'
NEW_SANDBOX = (
    '# caddy sandbox 경로 (write_script / run_script 전용)\n'
    'CADDY_SANDBOX = os.path.join(ARSS_ROOT, "tools/sandbox/caddy/active")\n'
    '\n'
    '# git_push allowlist (Fail-Closed)'
)
assert OLD_SANDBOX in content, "[FAIL] 패턴 2(sandbox 상수) 미발견"
content = content.replace(OLD_SANDBOX, NEW_SANDBOX, 1)
print("변경 2 OK: CADDY_SANDBOX 상수 추가")

# ── 변경 3: COMMAND_TIMEOUTS에 write_script, run_script 추가 ─────────────────
OLD_TIMEOUTS = '    "git_push": 120,\n    "systemctl_restart": 30,'
NEW_TIMEOUTS = (
    '    "git_push": 120,\n'
    '    "systemctl_restart": 30,\n'
    '    "write_script": 10,\n'
    '    "run_script": 120,'
)
assert OLD_TIMEOUTS in content, "[FAIL] 패턴 3(timeouts) 미발견"
content = content.replace(OLD_TIMEOUTS, NEW_TIMEOUTS, 1)
print("변경 3 OK: write_script/run_script 타임아웃 추가")

# ── 변경 4: _validate_and_build_cmd에 분기 추가 ───────────────────────────────
OLD_VALIDATE_END = (
    '    return False, f"command \'{command}\' not in whitelist", []\n'
)
NEW_VALIDATE_END = (
    '    if command == "write_script":\n'
    '        filename = params.get("filename", "")\n'
    '        script_content = params.get("content", "")\n'
    '\n'
    '        if not filename:\n'
    '            return False, "write_script: filename required", []\n'
    '        if not filename.endswith(".py"):\n'
    '            return False, f"write_script: filename must end with .py: {filename!r}", []\n'
    '        if "/" in filename or "\\\\" in filename:\n'
    '            return False, f"write_script: path separator not allowed in filename: {filename!r}", []\n'
    '        if not script_content:\n'
    '            return False, "write_script: content required", []\n'
    '\n'
    '        os.makedirs(CADDY_SANDBOX, exist_ok=True)\n'
    '        target = os.path.realpath(os.path.join(CADDY_SANDBOX, filename))\n'
    '        real_sandbox = os.path.realpath(CADDY_SANDBOX)\n'
    '        if not (target == real_sandbox or target.startswith(real_sandbox + os.sep)):\n'
    '            return False, f"write_script: path escape detected: {target!r}", []\n'
    '\n'
    '        spec = {"command": "write_script", "target": target, "content": script_content}\n'
    '        return True, "", spec\n'
    '\n'
    '    if command == "run_script":\n'
    '        script_path = params.get("script_path", "")\n'
    '\n'
    '        if not script_path:\n'
    '            return False, "run_script: script_path required", []\n'
    '        if not script_path.endswith(".py"):\n'
    '            return False, f"run_script: script_path must end with .py: {script_path!r}", []\n'
    '\n'
    '        real_script = os.path.realpath(os.path.abspath(script_path))\n'
    '        real_sandbox = os.path.realpath(CADDY_SANDBOX)\n'
    '        if not (real_script == real_sandbox or real_script.startswith(real_sandbox + os.sep)):\n'
    '            return False, f"run_script: path outside caddy sandbox: {real_script!r}", []\n'
    '        if not os.path.isfile(real_script):\n'
    '            return False, f"run_script: script not found: {real_script!r}", []\n'
    '\n'
    '        cmd = ["python3", real_script]\n'
    '        return True, "", cmd\n'
    '\n'
    '    return False, f"command \'{command}\' not in whitelist", []\n'
)
assert OLD_VALIDATE_END in content, "[FAIL] 패턴 4(validate end) 미발견"
content = content.replace(OLD_VALIDATE_END, NEW_VALIDATE_END, 1)
print("변경 4 OK: write_script/run_script 검증 분기 추가")

# ── 변경 5: _run_command에 write_script 처리 추가 ─────────────────────────────
OLD_RUN_START = (
    '        if command == "git_push":\n'
    '            push_spec = cmd_list  # push_spec dict'
)
NEW_RUN_START = (
    '        if command == "write_script":\n'
    '            spec = cmd_list  # write_script spec dict\n'
    '            try:\n'
    '                with open(spec["target"], "w", encoding="utf-8") as f:\n'
    '                    f.write(spec["content"])\n'
    '                return {\n'
    '                    "stdout": f"WRITE_OK: {spec[\'target\']}",\n'
    '                    "stderr": "",\n'
    '                    "exit_code": 0,\n'
    '                    "written_path": spec["target"],\n'
    '                }\n'
    '            except Exception as e:\n'
    '                return {"stdout": "", "stderr": f"WRITE_ERROR: {e}", "exit_code": -1}\n'
    '\n'
    '        if command == "git_push":\n'
    '            push_spec = cmd_list  # push_spec dict'
)
assert OLD_RUN_START in content, "[FAIL] 패턴 5(run_command write_script) 미발견"
content = content.replace(OLD_RUN_START, NEW_RUN_START, 1)
print("변경 5 OK: _run_command write_script 처리 추가")

# ── 변경 6: 응답에 write_script/run_script 전용 필드 추가 ────────────────────
OLD_RESP = (
    '        # git_push 전용 응답 필드 추가\n'
    '        if command == "git_push":'
)
NEW_RESP = (
    '        # write_script 전용 응답 필드 추가\n'
    '        if command == "write_script":\n'
    '            response["written_path"] = exec_result.get("written_path")\n'
    '\n'
    '        # git_push 전용 응답 필드 추가\n'
    '        if command == "git_push":'
)
assert OLD_RESP in content, "[FAIL] 패턴 6(응답 필드) 미발견"
content = content.replace(OLD_RESP, NEW_RESP, 1)
print("변경 6 OK: write_script 응답 필드 추가")

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)

print(f"PATCH COMPLETE: {PATH}")

# ── 검증 ──────────────────────────────────────────────────────────────────────
with open(PATH, "r", encoding="utf-8") as f:
    verify = f.read()

assert 'EXEC_RUNTIME_VERSION = "1.4.0"' in verify, "[FAIL] 버전"
assert "CADDY_SANDBOX" in verify,                  "[FAIL] CADDY_SANDBOX"
assert '"write_script": 10' in verify,             "[FAIL] write_script timeout"
assert '"run_script": 120' in verify,              "[FAIL] run_script timeout"
assert 'command == "write_script"' in verify,      "[FAIL] write_script 분기"
assert 'command == "run_script"' in verify,        "[FAIL] run_script 분기"
assert "written_path" in verify,                   "[FAIL] written_path 응답"
assert 'EXEC_RUNTIME_VERSION = "1.3.0"' not in verify, "[FAIL] 구 버전 잔존"

print("검증 PASS: 6개 변경 모두 확인 완료")
