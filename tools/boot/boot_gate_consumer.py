#!/usr/bin/env python3
"""
boot_gate_consumer.py  —  DEP-S256-BOOT-STABLE-001
캐디 BOOT Step 2-B 소비 로직.

read_file로 boot_gate_last_result.json을 읽은 후
이 스크립트로 유효성 검사. exit 0 = PASS, non-zero = FAIL_CLOSED.
"""
import json, sys, time, os

OUT_DIR   = "/opt/arss/engine/arss-protocol/tools/boot"
RESULT    = f"{OUT_DIR}/boot_gate_last_result.json"
FLAG      = f"{OUT_DIR}/BOOT_GATE_FAIL_FLAG"
FRESH_SEC = 3600  # 신선도 창

def main():
    # 1. 플래그 파일 확인 (systemd 실패 연동)
    if os.path.exists(FLAG):
        print(f"FAIL_CLOSED: BOOT_GATE_FAIL_FLAG 존재. systemd unit 실패 이력.")
        sys.exit(10)

    # 2. 결과 파일 존재 확인
    if not os.path.exists(RESULT):
        print("FAIL_CLOSED: boot_gate_last_result.json 부재 — 게이트 미실행.")
        sys.exit(11)

    # 3. 파일 읽기
    try:
        with open(RESULT) as f:
            r = json.load(f)
    except Exception as e:
        print(f"FAIL_CLOSED: 결과 파일 파싱 오류: {e}")
        sys.exit(12)

    # 4. 신선도 검증
    epoch = r.get("timestamp_epoch", 0)
    now   = time.time()
    age   = now - epoch
    fresh = r.get("fresh_window_sec", FRESH_SEC)
    if age > fresh:
        print(f"FAIL_CLOSED: 결과 오래됨 ({age:.0f}초 > {fresh}초). 게이트 재실행 필요.")
        sys.exit(13)

    # 5. 단조성 확인
    if not r.get("monotonic_ok"):
        print(f"FAIL_CLOSED: 단조성 실패: {r.get('fail_reason')}")
        sys.exit(14)

    # 6. 해시 일치 확인
    if not r.get("whitelist_hash_match"):
        print(f"FAIL_CLOSED: 화이트리스트 해시 불일치: {r.get('fail_reason')}")
        sys.exit(15)

    # 7. 게이트 exit code 확인
    if r.get("status") != "PASS" or r.get("exit_code") != 0:
        print(f"FAIL_CLOSED: 게이트 FAIL: {r.get('fail_reason')}")
        sys.exit(r.get("exit_code") or 16)

    # 8. 전체 PASS
    print(f"BOOT-GATE PASS | session={r.get('session_id')} | "
          f"hash={r.get('gate_file_hash','?')[:12]}... | "
          f"age={age:.0f}s | monotonic=OK")
    sys.exit(0)

if __name__ == "__main__":
    main()
