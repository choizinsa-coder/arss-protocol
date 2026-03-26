#!/usr/bin/env python3
"""
preflight_check.py
==================
ARSS Workflow Pre-flight Check Script

실행 전 환경 및 상태를 자동 점검한다.
9개 항목 전체 PASS 시 exit code 0 반환.
1개라도 FAIL 시 exit code 1 반환.

저장 경로: arss-protocol/scripts/workflow/preflight_check.py
작성: Cadi (Claude) | 승인: Joshua (비오) | 2026-03-26
RGO v2.0 Rev.1 준수 | ARSS-RPU-Production-Spec-v1.0 기준
"""

import sys
import subprocess
import importlib
import os
import json

# ── 설정 ──────────────────────────────────────────────────
VPS_HOST = "root@159.203.125.1"
VPS_SSH_TIMEOUT = 10
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
)))

REQUIRED_MODULES = ["hashlib", "json", "subprocess", "pathlib"]
REQUIRED_PYTHON = (3, 8)

GENERATOR_PATH = os.path.join(REPO_ROOT, "arss_generator_v1.py")
VERIFIER_PATH  = os.path.join(
    REPO_ROOT, "reference-verifier", "src", "verifier.py"
)
BRIDGE_PATH    = os.path.join(REPO_ROOT, "vps_verifier_bridge.py")
LEDGER_PATH    = os.path.join(
    REPO_ROOT, "ARSS_HUB", "04_EVIDENCE", "SNAPSHOT_LOG", "ledger.json"
)
APPROVAL_TOKEN_PATH = os.path.join(
    REPO_ROOT, "scripts", "workflow", ".approval_token"
)

# ── 결과 추적 ──────────────────────────────────────────────
results = []


def check(name, passed, detail=""):
    """점검 항목 결과를 기록하고 출력한다."""
    status = "PASS" if passed else "FAIL"
    symbol = "✅" if passed else "❌"
    msg = f"  {symbol} [{status}] {name}"
    if detail:
        msg += f"\n         → {detail}"
    print(msg)
    results.append((name, passed))


# ── CHECK 1: Python 버전 ───────────────────────────────────
def check_python_version():
    """Python 버전이 요구 사항을 충족하는지 확인한다."""
    current = sys.version_info[:2]
    passed = current >= REQUIRED_PYTHON
    detail = f"현재: {current[0]}.{current[1]} / 요구: {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+"
    check("Python 버전", passed, detail)


# ── CHECK 2: 필수 모듈 ────────────────────────────────────
def check_required_modules():
    """필수 Python 모듈이 모두 import 가능한지 확인한다."""
    missing = []
    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    passed = len(missing) == 0
    detail = (
        f"전체 {len(REQUIRED_MODULES)}개 정상"
        if passed
        else f"누락: {', '.join(missing)}"
    )
    check("필수 모듈", passed, detail)


# ── CHECK 3: Generator 파일 존재 ──────────────────────────
def check_generator():
    """arss_generator_v1.py 파일이 존재하는지 확인한다."""
    passed = os.path.isfile(GENERATOR_PATH)
    detail = GENERATOR_PATH if passed else f"파일 없음: {GENERATOR_PATH}"
    check("Generator (arss_generator_v1.py)", passed, detail)


# ── CHECK 4: Verifier 파일 존재 ───────────────────────────
def check_verifier():
    """reference-verifier/src/verifier.py 파일이 존재하는지 확인한다."""
    passed = os.path.isfile(VERIFIER_PATH)
    detail = VERIFIER_PATH if passed else f"파일 없음: {VERIFIER_PATH}"
    check("Verifier (reference-verifier/src/verifier.py)", passed, detail)


# ── CHECK 5: ledger.json 존재 및 파싱 ────────────────────
def check_ledger():
    """ledger.json이 존재하고 유효한 JSON인지 확인한다."""
    if not os.path.isfile(LEDGER_PATH):
        check("ledger.json", False, f"파일 없음: {LEDGER_PATH}")
        return
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        tip = data.get("chain_tip", data.get("tip", "unknown"))
        check("ledger.json", True, f"chain_tip: {str(tip)[:20]}...")
    except (json.JSONDecodeError, Exception) as e:
        check("ledger.json", False, f"파싱 오류: {e}")


# ── CHECK 6: Git 상태 (clean 여부) ────────────────────────
def check_git_clean():
    """워킹 디렉토리에 uncommitted 변경사항이 없는지 확인한다."""
    try:
        result = subprocess.run(
            ["git", "-C", REPO_ROOT, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10
        )
        passed = result.returncode == 0 and result.stdout.strip() == ""
        detail = (
            "uncommitted 변경사항 없음"
            if passed
            else f"미커밋 변경: {result.stdout.strip()[:80]}"
        )
        check("Git 상태 (clean)", passed, detail)
    except Exception as e:
        check("Git 상태 (clean)", False, f"Git 실행 오류: {e}")


# ── CHECK 7: Git remote origin ───────────────────────────
def check_git_origin():
    """Git remote origin이 설정되어 있는지 확인한다."""
    try:
        result = subprocess.run(
            ["git", "-C", REPO_ROOT, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10
        )
        passed = result.returncode == 0 and result.stdout.strip() != ""
        detail = (
            result.stdout.strip()
            if passed
            else "origin 미설정"
        )
        check("Git remote origin", passed, detail)
    except Exception as e:
        check("Git remote origin", False, f"Git 실행 오류: {e}")


# ── CHECK 8: Approval Token ──────────────────────────────
def check_approval_token():
    """scripts/workflow/.approval_token 파일이 존재하는지 확인한다."""
    passed = os.path.isfile(APPROVAL_TOKEN_PATH)
    detail = (
        "approval_token 확인됨"
        if passed
        else f"파일 없음: {APPROVAL_TOKEN_PATH}"
    )
    check("Approval Token", passed, detail)


# ── CHECK 9: VPS SSH 연결 ────────────────────────────────
def check_vps_ssh():
    """VPS SSH 연결이 가능한지 확인한다 (BatchMode=yes, 실제 연결)."""
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={VPS_SSH_TIMEOUT}",
                "-o", "StrictHostKeyChecking=no",
                VPS_HOST,
                "echo VPS_OK"
            ],
            capture_output=True, text=True, timeout=VPS_SSH_TIMEOUT + 5
        )
        passed = (
            result.returncode == 0
            and "VPS_OK" in result.stdout
        )
        detail = (
            f"응답: {result.stdout.strip()}"
            if passed
            else f"연결 실패 (code {result.returncode}): {result.stderr.strip()[:80]}"
        )
        check("VPS SSH 연결 (159.203.125.1)", passed, detail)
    except subprocess.TimeoutExpired:
        check("VPS SSH 연결 (159.203.125.1)", False, f"타임아웃 ({VPS_SSH_TIMEOUT}초)")
    except Exception as e:
        check("VPS SSH 연결 (159.203.125.1)", False, f"실행 오류: {e}")


# ── 메인 ─────────────────────────────────────────────────
def main():
    """9개 항목 순차 점검 후 종합 결과를 출력한다."""
    print("=" * 60)
    print("  ARSS Pre-flight Check")
    print(f"  REPO_ROOT: {REPO_ROOT}")
    print("=" * 60)

    check_python_version()
    check_required_modules()
    check_generator()
    check_verifier()
    check_ledger()
    check_git_clean()
    check_git_origin()
    check_approval_token()
    check_vps_ssh()

    print("=" * 60)
    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    all_pass = passed_count == total

    if all_pass:
        print(f"  RESULT: ALL PASS ({passed_count}/{total})")
        print("  → 워크플로우 실행 조건 충족")
    else:
        failed = [name for name, p in results if not p]
        print(f"  RESULT: FAIL ({passed_count}/{total} PASS)")
        print(f"  → FAIL 항목: {', '.join(failed)}")
        print("  → 워크플로우 실행 중단")
    print("=" * 60)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
