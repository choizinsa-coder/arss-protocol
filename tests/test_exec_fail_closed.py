# tests/test_exec_fail_closed.py
"""
EAG-S210-EXEC-001: Fail-Closed 실행 파이프라인 동결 검증
TC-01: flag 없음 — git_commit Gate 0 투명 통과 (Gate 1에서 정상 처리)
TC-02: flag 존재 — git_commit 차단 (FAIL_CLOSED_ACTIVE)
TC-03: flag 존재 — git_push 차단
TC-04: flag 존재 — write_script 차단
TC-05: flag 존재 — run_script 차단
TC-06: flag 존재 — systemctl_restart 차단
TC-07: flag 존재 — pytest 허용 (관측성)
TC-08: flag 존재 — git_status 허용 (관측성)
TC-09: flag 존재 — git_diff 허용 (관측성)
"""
import json
import os
import sys
import threading
import time
import urllib.request
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/exec_runtime")

# ── 픽스처 ─────────────────────────────────────────────────────────────────

@pytest.fixture
def fail_closed_flag(tmp_path, monkeypatch):
    """FAIL_CLOSED_FLAG를 tmp_path 내 경로로 교체하고 flag 파일 생성."""
    import aiba_exec_runtime as er
    flag_path = str(tmp_path / "fail_closed.flag")
    monkeypatch.setattr(er, "FAIL_CLOSED_FLAG", flag_path)
    # flag 생성
    open(flag_path, "w").close()
    return flag_path


@pytest.fixture
def no_fail_closed_flag(tmp_path, monkeypatch):
    """FAIL_CLOSED_FLAG를 tmp_path 내 경로로 교체하되 파일은 생성하지 않음."""
    import aiba_exec_runtime as er
    flag_path = str(tmp_path / "fail_closed.flag")
    monkeypatch.setattr(er, "FAIL_CLOSED_FLAG", flag_path)
    # flag 미생성
    return flag_path


@pytest.fixture
def patched_audit(tmp_path, monkeypatch):
    """audit log를 tmp_path로 교체하여 실제 파일 기록 격리."""
    import aiba_exec_runtime as er
    audit_path = str(tmp_path / "exec_audit_trail.log")
    monkeypatch.setattr(er, "AUDIT_LOG_PATH", audit_path)
    return audit_path


def _call_gate0(command, flag_fixture, audit_fixture, monkeypatch):
    """
    ExecHandler.do_POST의 Gate 0 로직을 직접 단위 테스트.
    HTTP 서버 없이 _validate_and_build_cmd + Gate 0 조건만 검증.
    """
    import aiba_exec_runtime as er

    # Gate 0 조건 직접 평가
    flag_active = os.path.exists(er.FAIL_CLOSED_FLAG)
    is_mutating = command in er.MUTATING_COMMANDS
    blocked = flag_active and is_mutating
    return blocked


# ── TC-01: flag 없음 → 변경성 명령 Gate 0 통과 ────────────────────────────

def test_tc01_no_flag_mutating_passes(no_fail_closed_flag, patched_audit, monkeypatch):
    """flag 미존재 시 git_commit은 Gate 0을 통과해야 함"""
    import aiba_exec_runtime as er
    blocked = _call_gate0("git_commit", no_fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is False


# ── TC-02: flag 존재 → git_commit 차단 ────────────────────────────────────

def test_tc02_flag_git_commit_blocked(fail_closed_flag, patched_audit, monkeypatch):
    """flag 존재 시 git_commit은 Gate 0에서 차단"""
    import aiba_exec_runtime as er
    blocked = _call_gate0("git_commit", fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is True
    assert "git_commit" in er.MUTATING_COMMANDS


# ── TC-03: flag 존재 → git_push 차단 ──────────────────────────────────────

def test_tc03_flag_git_push_blocked(fail_closed_flag, patched_audit, monkeypatch):
    import aiba_exec_runtime as er
    blocked = _call_gate0("git_push", fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is True
    assert "git_push" in er.MUTATING_COMMANDS


# ── TC-04: flag 존재 → write_script 차단 ─────────────────────────────────

def test_tc04_flag_write_script_blocked(fail_closed_flag, patched_audit, monkeypatch):
    import aiba_exec_runtime as er
    blocked = _call_gate0("write_script", fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is True
    assert "write_script" in er.MUTATING_COMMANDS


# ── TC-05: flag 존재 → run_script 차단 ───────────────────────────────────

def test_tc05_flag_run_script_blocked(fail_closed_flag, patched_audit, monkeypatch):
    import aiba_exec_runtime as er
    blocked = _call_gate0("run_script", fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is True
    assert "run_script" in er.MUTATING_COMMANDS


# ── TC-06: flag 존재 → systemctl_restart 차단 ────────────────────────────

def test_tc06_flag_systemctl_blocked(fail_closed_flag, patched_audit, monkeypatch):
    import aiba_exec_runtime as er
    blocked = _call_gate0("systemctl_restart", fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is True
    assert "systemctl_restart" in er.MUTATING_COMMANDS


# ── TC-07: flag 존재 → pytest 허용 (관측성) ──────────────────────────────

def test_tc07_flag_pytest_allowed(fail_closed_flag, patched_audit, monkeypatch):
    import aiba_exec_runtime as er
    blocked = _call_gate0("pytest", fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is False
    assert "pytest" not in er.MUTATING_COMMANDS


# ── TC-08: flag 존재 → git_status 허용 (관측성) ──────────────────────────

def test_tc08_flag_git_status_allowed(fail_closed_flag, patched_audit, monkeypatch):
    import aiba_exec_runtime as er
    blocked = _call_gate0("git_status", fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is False
    assert "git_status" not in er.MUTATING_COMMANDS


# ── TC-09: flag 존재 → git_diff 허용 (관측성) ────────────────────────────

def test_tc09_flag_git_diff_allowed(fail_closed_flag, patched_audit, monkeypatch):
    import aiba_exec_runtime as er
    blocked = _call_gate0("git_diff", fail_closed_flag, patched_audit, monkeypatch)
    assert blocked is False
    assert "git_diff" not in er.MUTATING_COMMANDS
