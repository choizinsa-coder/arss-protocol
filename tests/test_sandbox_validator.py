"""
test_sandbox_validator.py
AIBA SANDBOX Validator 단위 테스트 (S142)
RULE-3 이동: tools/ → tests/ (S153)
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools import sandbox_validator as sv

SANDBOX_ROOT = sv.SANDBOX_ROOT


# ── 파일명 파싱 ────────────────────────────────────────────────────────────

def test_parse_task_filename_basic():
    result = sv.parse_task_filename("task-S142-001-domi-design.md")
    assert result is not None
    assert result["session"] == "S142"
    assert result["id"] == "001"
    assert result["agent"] == "domi"
    assert result["type"] == "design"
    assert result["mode"] == "task"


def test_parse_task_filename_comment():
    result = sv.parse_task_filename(
        "task-S142-001-jeni-comment-on-domi-design-20260521143022.md"
    )
    assert result is not None
    assert result["commenter"] == "jeni"
    assert result["source_agent"] == "domi"
    assert result["source_type"] == "design"
    assert result["seq"] == "20260521143022"
    assert result["kind"] == "comment"


def test_parse_monitor_filename_basic():
    result = sv.parse_monitor_filename("monitor-20260521-jeni-finding.md")
    assert result is not None
    assert result["date"] == "20260521"
    assert result["agent"] == "jeni"
    assert result["type"] == "finding"
    assert result["mode"] == "monitor"


def test_parse_monitor_filename_comment():
    result = sv.parse_monitor_filename(
        "monitor-20260521-caddy-comment-on-jeni-warning-20260521090000.md"
    )
    assert result is not None
    assert result["commenter"] == "caddy"
    assert result["source_agent"] == "jeni"
    assert result["kind"] == "comment"


def test_parse_filename_prefix_task():
    result = sv.parse_filename("task-S142-001-caddy-review.md")
    assert result is not None
    assert result["mode"] == "task"


def test_parse_filename_prefix_monitor():
    result = sv.parse_filename("monitor-20260521-domi-status.md")
    assert result is not None
    assert result["mode"] == "monitor"


def test_parse_filename_unknown_prefix():
    result = sv.parse_filename("unknown-file.md")
    assert result is None


# ── type enum 검증 ─────────────────────────────────────────────────────────

def test_task_type_valid():
    parsed = {"mode": "task", "type": "design"}
    assert sv.validate_type_enum(parsed) is True


def test_task_type_invalid():
    parsed = {"mode": "task", "type": "invalid_type"}
    assert sv.validate_type_enum(parsed) is False


def test_monitor_type_valid():
    parsed = {"mode": "monitor", "type": "escalation"}
    assert sv.validate_type_enum(parsed) is True


def test_monitor_type_invalid():
    parsed = {"mode": "monitor", "type": "eag_pre_package"}
    assert sv.validate_type_enum(parsed) is False


def test_type_no_hyphen_rule():
    parsed = {"mode": "task", "type": "final-draft"}
    assert sv.validate_type_enum(parsed) is False


# ── validate_write 12단계 ──────────────────────────────────────────────────

def _valid_path(filename: str) -> str:
    return str(SANDBOX_ROOT / "domi" / "active" / filename)


def test_valid_write_allowed():
    path = _valid_path("task-S142-001-domi-design.md")
    with patch("os.path.realpath", return_value=path), \
         patch("pathlib.Path.is_symlink", return_value=False), \
         patch("pathlib.Path.exists", return_value=False):
        result = sv.validate_write(
            request_agent="domi",
            target_path_str=path,
            file_content=b"content",
            file_name="task-S142-001-domi-design.md",
            file_status="DRAFT",
        )
    assert result.allowed is True
    assert result.status_code == 200


def test_invalid_agent():
    result = sv.validate_write(
        request_agent="unknown_agent",
        target_path_str=_valid_path("task-S142-001-domi-design.md"),
        file_content=b"content",
        file_name="task-S142-001-domi-design.md",
    )
    assert result.allowed is False
    assert "INVALID_AGENT" in result.reason


def test_path_outside_sandbox():
    outside_path = "/opt/arss/engine/arss-protocol/tools/tmp/evil.md"
    with patch("os.path.realpath", return_value=outside_path):
        result = sv.validate_write(
            request_agent="domi",
            target_path_str=outside_path,
            file_content=b"content",
            file_name="task-S142-001-domi-design.md",
        )
    assert result.allowed is False
    assert "SANDBOX" in result.reason


def test_forbidden_extension():
    path = _valid_path("task-S142-001-domi-design.py")
    with patch("os.path.realpath", return_value=path):
        result = sv.validate_write(
            request_agent="domi",
            target_path_str=path,
            file_content=b"content",
            file_name="task-S142-001-domi-design.py",
        )
    assert result.allowed is False
    assert "FORBIDDEN_EXTENSION" in result.reason


def test_cross_overwrite_denied():
    filename = "task-S142-001-domi-design.md"
    path = _valid_path(filename)
    with patch("os.path.realpath", return_value=path), \
         patch("pathlib.Path.is_symlink", return_value=False), \
         patch("pathlib.Path.exists", return_value=True):
        result = sv.validate_write(
            request_agent="jeni",
            target_path_str=path,
            file_content=b"content",
            file_name=filename,
            file_status="DRAFT",
        )
    assert result.allowed is False
    assert "CROSS_OVERWRITE_DENIED" in result.reason


def test_file_too_large():
    path = _valid_path("task-S142-001-domi-design.md")
    with patch("os.path.realpath", return_value=path), \
         patch("pathlib.Path.is_symlink", return_value=False), \
         patch("pathlib.Path.exists", return_value=False):
        result = sv.validate_write(
            request_agent="domi",
            target_path_str=path,
            file_content=b"x" * (sv.MAX_FILE_SIZE_BYTES + 1),
            file_name="task-S142-001-domi-design.md",
        )
    assert result.allowed is False
    assert result.status_code == 413


def test_filename_parse_failed():
    path = _valid_path("invalid_filename.md")
    with patch("os.path.realpath", return_value=path), \
         patch("pathlib.Path.is_symlink", return_value=False), \
         patch("pathlib.Path.exists", return_value=False):
        result = sv.validate_write(
            request_agent="domi",
            target_path_str=path,
            file_content=b"content",
            file_name="invalid_filename.md",
        )
    assert result.allowed is False
    assert "FILENAME_PARSE_FAILED" in result.reason


# ── SAFE_PASS 판정 ─────────────────────────────────────────────────────────

def test_safe_pass_allowed_draft():
    paths = [_valid_path("task-S142-001-domi-design.md")]
    statuses = ["DRAFT"]
    result = sv.check_safe_pass_batch(
        request_agent="domi", file_paths=paths, file_statuses=statuses,
    )
    assert result.allowed is True


def test_safe_pass_denied_beo_pending():
    paths = [_valid_path("task-S142-001-domi-design.md")]
    statuses = ["BEO_PENDING"]
    result = sv.check_safe_pass_batch(
        request_agent="domi", file_paths=paths, file_statuses=statuses,
    )
    assert result.allowed is False
    assert "FSM_STATE_BLOCKED" in result.reason


def test_safe_pass_denied_approved():
    paths = [_valid_path("task-S142-001-domi-design.md")]
    statuses = ["APPROVED"]
    result = sv.check_safe_pass_batch(
        request_agent="domi", file_paths=paths, file_statuses=statuses,
    )
    assert result.allowed is False


def test_safe_pass_denied_file_count():
    paths = [_valid_path(f"task-S142-00{i}-domi-design.md") for i in range(4)]
    statuses = ["DRAFT"] * 4
    result = sv.check_safe_pass_batch(
        request_agent="domi", file_paths=paths, file_statuses=statuses,
    )
    assert result.allowed is False
    assert "FILE_COUNT_EXCEEDED" in result.reason


def test_safe_pass_denied_service_restart():
    paths = [_valid_path("task-S142-001-domi-design.md")]
    statuses = ["DRAFT"]
    result = sv.check_safe_pass_batch(
        request_agent="domi", file_paths=paths, file_statuses=statuses,
        service_restart=True,
    )
    assert result.allowed is False
    assert "SERVICE_RESTART_FORBIDDEN" in result.reason


def test_safe_pass_denied_tmp_path():
    tmp_path = str(sv.TMP_PATH / "task-S142-001-domi-design.md")
    result = sv.check_safe_pass_batch(
        request_agent="domi", file_paths=[tmp_path], file_statuses=["DRAFT"],
    )
    assert result.allowed is False
    assert "TMP_PATH_EXCLUDED" in result.reason
