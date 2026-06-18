#!/usr/bin/env python3
"""
boot_gate_runner.py  —  DEP-S256-BOOT-STABLE-001
EAG: EAG-S256-BOOT-STABLE-001

역할: govdoc_freeze_gate.py를 실행하고 결과를
      tools/boot/boot_gate_last_result.json 에 기록.
      캐디 BOOT Step 2-B는 이 파일을 read_file로 소비.

화이트리스트: GATE_SCRIPT 경로만 실행 허용. 임의 경로 거부.
단조성: 이전 timestamp보다 항상 큰 epoch 강제.
해시 재검증: 실행 전 GATE_SCRIPT 해시를 EAG 등록값과 비교.
"""
import json, hashlib, os, subprocess, sys, time
from datetime import datetime, timezone

BASE         = "/opt/arss/engine/arss-protocol"
GATE_SCRIPT  = f"{BASE}/tools/guard/govdoc_freeze_gate.py"  # 화이트리스트 고정
OUT_DIR      = f"{BASE}/tools/boot"
OUT_FILE     = f"{OUT_DIR}/boot_gate_last_result.json"
MONO_FILE    = f"{OUT_DIR}/boot_gate_monotonic.json"
HASH_REG     = f"{OUT_DIR}/gate_whitelist_hash.txt"
FRESH_WINDOW = 7200  # 신선도 창 2시간

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def env_info():
    import platform
    return {
        "python": sys.version.split()[0],
        "os": platform.system(),
        "os_release": platform.release(),
        "hostname": os.uname().nodename,
    }

def load_mono():
    try:
        with open(MONO_FILE) as f:
            return json.load(f)
    except Exception:
        return {"last_epoch": 0}

def save_mono(epoch, session_id):
    tmp = MONO_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"last_epoch": epoch, "last_session": session_id}, f)
    os.replace(tmp, MONO_FILE)

def write_result(result, code):
    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    os.replace(tmp, OUT_FILE)
    print(f"[BOOT-GATE] status={result['status']} exit={code} reason={result.get('fail_reason')}")
    sys.exit(code)

def run():
    os.makedirs(OUT_DIR, exist_ok=True)
    now   = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()
    sid   = os.environ.get("AIBA_SESSION_ID", f"AUTO-{int(now)}")

    r = {
        "schema": "boot_gate_result_v1",
        "eag": "EAG-S256-BOOT-STABLE-001",
        "session_id": sid,
        "timestamp_epoch": now,
        "timestamp_iso": now_iso,
        "fresh_window_sec": FRESH_WINDOW,
        "gate_script": GATE_SCRIPT,
        "gate_file_hash": None,
        "whitelist_hash_match": None,
        "monotonic_ok": None,
        "exit_code": None,
        "status": "FAIL",
        "fail_reason": None,
        "env": env_info(),
    }

    # 1. 게이트 스크립트 존재 확인
    if not os.path.isfile(GATE_SCRIPT):
        r["fail_reason"] = f"GATE_NOT_FOUND: {GATE_SCRIPT}"
        write_result(r, 1)

    # 2. 화이트리스트 해시 재검증 (실행 시점)
    cur_hash = sha256_file(GATE_SCRIPT)
    r["gate_file_hash"] = cur_hash

    if os.path.exists(HASH_REG):
        with open(HASH_REG) as f:
            eag_hash = f.read().strip()
        if cur_hash != eag_hash:
            r["whitelist_hash_match"] = False
            r["fail_reason"] = f"HASH_MISMATCH: expected={eag_hash} got={cur_hash}"
            write_result(r, 2)
        r["whitelist_hash_match"] = True
    else:
        # 최초 배포: 현재 해시를 EAG 기준값으로 등록
        with open(HASH_REG, "w") as f:
            f.write(cur_hash)
        r["whitelist_hash_match"] = True
        print(f"[BOOT-GATE] 최초 해시 등록: {cur_hash}")

    # 3. 단조성 검증
    mono = load_mono()
    last = mono.get("last_epoch", 0)
    if now <= last:
        r["monotonic_ok"] = False
        r["fail_reason"] = f"NOT_MONOTONIC: now={now} <= last={last}"
        write_result(r, 3)
    r["monotonic_ok"] = True

    # 4. 게이트 실행 (화이트리스트 고정 경로만)
    try:
        proc = subprocess.run(
            [sys.executable, GATE_SCRIPT],
            capture_output=True, text=True, timeout=30
        )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        r["fail_reason"] = "GATE_TIMEOUT"
        write_result(r, 4)
    except Exception as e:
        r["fail_reason"] = f"GATE_EXEC_ERROR: {e}"
        write_result(r, 5)

    r["exit_code"] = exit_code
    if exit_code != 0:
        r["fail_reason"] = f"GATE_NONZERO: {exit_code}"
        write_result(r, exit_code)

    # 5. 성공 시 단조성 갱신
    save_mono(now, sid)
    r["status"] = "PASS"
    write_result(r, 0)

if __name__ == "__main__":
    run()
