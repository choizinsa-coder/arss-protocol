ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
enforcement_gate.py — Code Health Enforcement Layer v1.0
AIBA Code Health Protocol
EAG-3 진입 전 실행 차단 게이트 (메인)

Activation Conditions (비오 EAG-3 MANDATORY):
1. 모든 EAG-3 진입 경로 선행 실행 필수
2. pass=false → 즉시 차단, override 금지
3. FAIL 항목 1개라도 존재 → BLOCKED
4. validator 내부 exception → 자동 FAIL (fail-closed)
5. HARD REQUIREMENT — OPTIONAL 아님
"""

import os
from typing import List, Dict, Any, Optional
from enum import Enum

from tools.code_health.rule_loader import GATE_ID, LAYER_VERSION, SEVERITY_FAIL
from tools.code_health import domain_validator, principle_validator
from tools.code_health.violation_report import (
    build_report,
    build_exception_report,
    format_report,
    is_blocked,
)


class ScanMode(Enum):
    FULL_SCAN = "FULL_SCAN"
    DIFF_ONLY = "DIFF_ONLY"


def _collect_all_py_files(root_dir: str) -> List[str]:
    collected = []
    exclude_dirs = {"venv", ".venv", "__pycache__", ".git", "node_modules", "99_LEGACY"}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for filename in filenames:
            if filename.endswith(".py"):
                collected.append(os.path.join(dirpath, filename))
    return collected


def evaluate(
    root_dir: str,
    target_files: Optional[List[str]] = None,
    mode: ScanMode = ScanMode.DIFF_ONLY,
) -> Dict[str, Any]:
    try:
        if mode == ScanMode.FULL_SCAN:
            files = _collect_all_py_files(root_dir)
        else:
            if not target_files:
                return build_exception_report(
                    rule_id="GATE",
                    file=root_dir,
                    exc=ValueError("DIFF_ONLY mode requires target_files"),
                )
            files = target_files

        total_checked = len(files)
        domain_violations = domain_validator.evaluate(root_dir, files)
        principle_violations = principle_validator.evaluate(root_dir, files)
        all_violations = domain_violations + principle_violations
        report = build_report(violations=all_violations, total_checked=total_checked)
        return report

    except Exception as exc:
        return build_exception_report(rule_id="GATE", file=root_dir, exc=exc)


def enforce(
    root_dir: str,
    target_files: Optional[List[str]] = None,
    mode: ScanMode = ScanMode.DIFF_ONLY,
) -> None:
    report = evaluate(root_dir, target_files, mode)
    print(format_report(report))
    if is_blocked(report):
        fail_count = report["summary"]["fail_count"]
        raise SystemExit(
            "[CODE_HEALTH GATE] BLOCKED — "
            + str(fail_count) + " FAIL item(s) detected. "
            + "EAG-3 진입 금지. Remediation 완료 후 재실행 필요."
        )
if __name__ == "__main__":
    import sys
    mode = ScanMode.FULL_SCAN if "--full" in sys.argv else ScanMode.DIFF_ONLY
    enforce(".", mode=mode)
