"""
sandbox_validator.py
AIBA SANDBOX Write Validator — Layer 2 (L2-3, L2-7)
SSOT: BRIEFING-DOMI-S142-DESIGN-REQUEST-FINAL
"""

import logging as _logging
import os
import re
import mimetypes
from pathlib import Path
from typing import Optional

# ── 상수 ───────────────────────────────────────────────────────────────────

SANDBOX_ROOT = Path("/opt/arss/engine/arss-protocol/tools/sandbox")
TMP_PATH     = Path("/opt/arss/engine/arss-protocol/tools/tmp")

ALLOWED_EXTENSIONS = {".md", ".json", ".txt"}
FORBIDDEN_EXTENSIONS = {
    ".py", ".sh", ".rs", ".env", ".yml", ".yaml",
    ".exe", ".so", ".dll", ".service"
}

ALLOWED_AGENTS = {"domi", "jeni", "caddy"}
ALLOWED_STATUSES = {
    "DRAFT", "IN_REVIEW", "BEO_PENDING", "EAG_READY", "APPROVED", "ARCHIVED"
}
SAFE_PASS_ALLOWED_STATUSES = {"DRAFT", "IN_REVIEW"}

# Task-Driven {type} enum
TASK_TYPE_ENUM = {
    "brief", "query", "response", "design", "review", "trust",
    "finding", "warning", "comment", "reference", "summary",
    "status", "final_draft", "eag_pre_package"
}

# Monitoring-Driven {type} enum
MONITOR_TYPE_ENUM = {
    "finding", "warning", "note", "review", "comment",
    "reference", "summary", "status", "escalation"
}

MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024  # 1MB
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 10

# ── 파싱 유틸 ──────────────────────────────────────────────────────────────

def parse_task_filename(name: str) -> Optional[dict]:
    """
    task-{session}-{id}-{agent}-{type}.md
    또는 comment:
    task-{session}-{id}-{commenter}-comment-on-{source_agent}-{source_type}-{seq}.md
    """
    if not name.startswith("task-"):
        return None
    parts = name
    # comment 패턴 우선 확인
    comment_pattern = re.compile(
        r'^task-(?P<session>[^-]+)-(?P<id>[^-]+)-(?P<commenter>[^-]+)'
        r'-comment-on-(?P<source_agent>[^-]+)-(?P<source_type>[^-]+)'
        r'-(?P<seq>\d{14})\.md$'
    )
    reference_pattern = re.compile(
        r'^task-(?P<session>[^-]+)-(?P<id>[^-]+)-(?P<commenter>[^-]+)'
        r'-reference-to-(?P<source_agent>[^-]+)-(?P<source_type>[^-]+)'
        r'-(?P<seq>\d{14})\.md$'
    )
    base_pattern = re.compile(
        r'^task-(?P<session>[^-]+)-(?P<id>[^-]+)-(?P<agent>[^-]+)'
        r'-(?P<type>[^.]+)\.md$'
    )
    for pattern, kind in [
        (comment_pattern, "comment"),
        (reference_pattern, "reference"),
        (base_pattern, "task"),
    ]:
        m = pattern.match(name)
        if m:
            result = m.groupdict()
            result["kind"] = kind
            result["mode"] = "task"
            return result
    return None


def parse_monitor_filename(name: str) -> Optional[dict]:
    """
    monitor-{yyyymmdd}-{agent}-{type}.md
    또는 comment:
    monitor-{yyyymmdd}-{commenter}-comment-on-{source_agent}-{source_type}-{seq}.md
    """
    if not name.startswith("monitor-"):
        return None
    comment_pattern = re.compile(
        r'^monitor-(?P<date>\d{8})-(?P<commenter>[^-]+)'
        r'-comment-on-(?P<source_agent>[^-]+)-(?P<source_type>[^-]+)'
        r'-(?P<seq>\d{14})\.md$'
    )
    reference_pattern = re.compile(
        r'^monitor-(?P<date>\d{8})-(?P<commenter>[^-]+)'
        r'-reference-to-(?P<source_agent>[^-]+)-(?P<source_type>[^-]+)'
        r'-(?P<seq>\d{14})\.md$'
    )
    base_pattern = re.compile(
        r'^monitor-(?P<date>\d{8})-(?P<agent>[^-]+)-(?P<type>[^.]+)\.md$'
    )
    for pattern, kind in [
        (comment_pattern, "comment"),
        (reference_pattern, "reference"),
        (base_pattern, "monitor"),
    ]:
        m = pattern.match(name)
        if m:
            result = m.groupdict()
            result["kind"] = kind
            result["mode"] = "monitor"
            return result
    return None


def parse_filename(name: str) -> Optional[dict]:
    """prefix 기준으로 모드 판별 후 파싱"""
    if name.startswith("task-"):
        return parse_task_filename(name)
    elif name.startswith("monitor-"):
        return parse_monitor_filename(name)
    return None


def validate_type_enum(parsed: dict) -> bool:
    """모드별 {type} enum 검증"""
    mode = parsed.get("mode")
    file_type = parsed.get("type") or parsed.get("source_type", "")
    if mode == "task":
        return file_type in TASK_TYPE_ENUM
    elif mode == "monitor":
        return file_type in MONITOR_TYPE_ENUM
    return False


def get_authorship_from_filename(name: str) -> Optional[str]:
    """파일명에서 작성자 에이전트 추출"""
    parsed = parse_filename(name)
    if not parsed:
        return None
    return parsed.get("agent") or parsed.get("commenter")

# ── 메인 검증 ─────────────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self, allowed: bool, status_code: int, reason: str):
        self.allowed = allowed
        self.status_code = status_code
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "status_code": self.status_code,
            "reason": self.reason
        }


# rate limit 상태 (in-memory, 프로세스 재시작 시 초기화)
_rate_limit_store: dict = {}


def validate_write(
    request_agent: str,
    target_path_str: str,
    file_content: bytes,
    file_name: str,
    file_status: Optional[str] = None,
    safe_pass_requested: bool = False,
) -> ValidationResult:
    """
    12단계 SANDBOX write 검증
    반환: ValidationResult(allowed, status_code, reason)
    """
    import time

    # ── Step 1: token agent 확인 ────────────────────────────────────────
    if request_agent not in ALLOWED_AGENTS:
        return ValidationResult(False, 403, f"INVALID_AGENT: {request_agent}")

    # ── Step 2: target_path 수신 ────────────────────────────────────────
    try:
        target_path = Path(target_path_str)
    except Exception:
        return ValidationResult(False, 400, "INVALID_PATH")

    # ── Step 3: realpath() 계산 ─────────────────────────────────────────
    try:
        real = Path(os.path.realpath(target_path_str))
    except Exception:
        return ValidationResult(False, 400, "REALPATH_FAILED")

    # ── Step 4: tools/sandbox/ prefix 강제 ─────────────────────────────
    try:
        real.relative_to(SANDBOX_ROOT)
    except ValueError:
        return ValidationResult(False, 403, "PATH_OUTSIDE_SANDBOX")

    # ── Step 5: symlink 거부 ────────────────────────────────────────────
    if target_path.is_symlink() or real != target_path.resolve():
        return ValidationResult(False, 403, "SYMLINK_DENIED")

    # ── Step 6: 확장자 whitelist 확인 ───────────────────────────────────
    suffix = Path(file_name).suffix.lower()
    if suffix in FORBIDDEN_EXTENSIONS:
        return ValidationResult(False, 403, f"FORBIDDEN_EXTENSION: {suffix}")
    if suffix not in ALLOWED_EXTENSIONS:
        return ValidationResult(False, 403, f"EXTENSION_NOT_ALLOWED: {suffix}")

    # ── Step 7: MIME 확인 ───────────────────────────────────────────────
    mime_type, _ = mimetypes.guess_type(file_name)
    allowed_mimes = {"text/plain", "text/markdown", "application/json", None}
    if mime_type not in allowed_mimes:
        return ValidationResult(False, 403, f"MIME_NOT_ALLOWED: {mime_type}")

    # ── Step 8: 파일 크기 확인 ──────────────────────────────────────────
    if len(file_content) > MAX_FILE_SIZE_BYTES:
        return ValidationResult(False, 413, "FILE_TOO_LARGE")

    # ── Step 9: 파일명 파싱 ─────────────────────────────────────────────
    parsed = parse_filename(file_name)
    if parsed is None:
        return ValidationResult(False, 400, "FILENAME_PARSE_FAILED")
    if not validate_type_enum(parsed):
        return ValidationResult(False, 400, f"INVALID_TYPE_ENUM: {parsed.get('type')}")

    # ── Step 10: 기존 파일이면 authorship 검사 ──────────────────────────
    if real.exists():
        existing_author = get_authorship_from_filename(file_name)
        if existing_author and existing_author != request_agent:
            return ValidationResult(
                False, 403,
                f"CROSS_OVERWRITE_DENIED: file owned by {existing_author}, "
                f"request from {request_agent}"
            )
        # ARCHIVED 파일: append-only archival metadata만 허용
        if file_status == "ARCHIVED":
            return ValidationResult(False, 403, "ARCHIVE_IMMUTABLE")

    # ── Step 11: rate limit 검사 ────────────────────────────────────────
    now = time.time()
    window_key = f"{request_agent}:{int(now // RATE_LIMIT_WINDOW_SECONDS)}"
    _rate_limit_store[window_key] = _rate_limit_store.get(window_key, 0) + 1
    if _rate_limit_store[window_key] > RATE_LIMIT_MAX_REQUESTS:
        return ValidationResult(False, 429, "RATE_LIMIT_EXCEEDED")

    # ── SAFE_PASS 판정 (Step 12 전처리) ─────────────────────────────────
    if safe_pass_requested:
        if file_status not in SAFE_PASS_ALLOWED_STATUSES:
            return ValidationResult(
                False, 403,
                f"SAFE_PASS_DENIED\nREASON=FSM_STATE_BLOCKED: {file_status}"
            )
        # tools/tmp/ 포함 여부 확인
        try:
            real.relative_to(TMP_PATH)
            return ValidationResult(False, 403, "SAFE_PASS_DENIED\nREASON=TMP_PATH_EXCLUDED")
        except ValueError as _rule6_e:
            _logging.debug("RULE6 sandbox_validator: %s", _rule6_e)

    # ── Step 12: write 허용 ─────────────────────────────────────────────
    return ValidationResult(True, 200, "ALLOW")


# ── SAFE_PASS 조건 일괄 검증 ───────────────────────────────────────────────

def check_safe_pass_batch(
    request_agent: str,
    file_paths: list[str],
    file_statuses: list[str],
    service_restart: bool = False,
    nginx_change: bool = False,
    systemd_change: bool = False,
    env_change: bool = False,
    critical_finding: bool = False,
) -> ValidationResult:
    """
    SAFE_PASS 일괄 조건 검증 (L2-7)
    """
    if len(file_paths) > 3:
        return ValidationResult(False, 403, "SAFE_PASS_DENIED\nREASON=FILE_COUNT_EXCEEDED")
    if service_restart:
        return ValidationResult(False, 403, "SAFE_PASS_DENIED\nREASON=SERVICE_RESTART_FORBIDDEN")
    if nginx_change or systemd_change or env_change:
        return ValidationResult(False, 403, "SAFE_PASS_DENIED\nREASON=INFRA_CHANGE_FORBIDDEN")
    if critical_finding:
        return ValidationResult(False, 403, "SAFE_PASS_DENIED\nREASON=CRITICAL_FINDING_PRESENT")

    for path_str, status in zip(file_paths, file_statuses):
        # tmp 포함 여부
        try:
            Path(os.path.realpath(path_str)).relative_to(TMP_PATH)
            return ValidationResult(False, 403, "SAFE_PASS_DENIED\nREASON=TMP_PATH_EXCLUDED")
        except ValueError as _rule6_e:
            _logging.debug("RULE6 sandbox_validator: %s", _rule6_e)
        # sandbox 내부 여부
        try:
            Path(os.path.realpath(path_str)).relative_to(SANDBOX_ROOT)
        except ValueError:
            return ValidationResult(False, 403, "SAFE_PASS_DENIED\nREASON=PATH_OUTSIDE_SANDBOX")
        # FSM 상태 확인
        if status not in SAFE_PASS_ALLOWED_STATUSES:
            return ValidationResult(
                False, 403,
                f"SAFE_PASS_DENIED\nREASON=FSM_STATE_BLOCKED: {status}"
            )

    return ValidationResult(True, 200, "SAFE_PASS_ALLOW")
