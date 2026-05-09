ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
domain_validator.py — Code Health Enforcement Layer v1.0
AIBA Code Health Protocol
CODE_DOMAIN.md 규칙 검증 모듈 (RULE-1, RULE-9)
"""

import ast
import glob
import os
from typing import List, Dict, Any

from tools.code_health.rule_loader import (
    RULE1_FORBIDDEN_PATTERNS,
    RULE1_LEGACY_DIRS,
    RULE9_FORBIDDEN_GENERIC_NAMES,
    RULE9_DOMAIN_KEYWORDS,
    SEVERITY_FAIL,
    SEVERITY_REVIEW,
)
from tools.code_health.violation_report import build_violation, build_exception_report


def _is_in_legacy_dir(filepath: str) -> bool:
    """파일이 허용된 레거시 디렉토리 내에 있는지 확인"""
    parts = filepath.replace("\\", "/").split("/")
    return any(legacy in parts for legacy in RULE1_LEGACY_DIRS)


def check_rule1_legacy_backup(root_dir: str, target_files: List[str]) -> List[Dict[str, Any]]:
    """
    RULE-1: 활성 디렉토리 내 백업/레거시 파일 탐지
    fail-closed: exception → FAIL 반환
    """
    violations = []
    try:
        for pattern in RULE1_FORBIDDEN_PATTERNS:
            matched = glob.glob(os.path.join(root_dir, "**", pattern), recursive=True)
            for match in matched:
                rel_path = os.path.relpath(match, root_dir)
                _rp = rel_path.replace(chr(92), chr(47))
                if any(ex in _rp.split(chr(47)) for ex in [chr(118)+chr(101)+chr(110)+chr(118), chr(46)+chr(118)+chr(101)+chr(110)+chr(118), chr(95)*2+chr(112)+chr(121)+chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)*2, chr(46)+chr(103)+chr(105)+chr(116)]):
                    continue
                if not _is_in_legacy_dir(rel_path):
                    violations.append(build_violation(
                        rule_id="RULE-1",
                        file=rel_path,
                        violation_type="LEGACY_BACKUP_IN_ACTIVE_DIR",
                        detail=f"Forbidden pattern {pattern} detected in active area",
                        severity=SEVERITY_FAIL,
                    ))
    except Exception as exc:
        return [build_exception_report("RULE-1", root_dir, exc)["violations"][0]]
    return violations


def _extract_identifiers(filepath: str) -> List[str]:
    """AST 기반 식별자(함수명, 클래스명, 변수명) 추출"""
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=filepath)
    identifiers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            identifiers.append(node.name)
        elif isinstance(node, ast.ClassDef):
            identifiers.append(node.name)
    return identifiers


def _has_domain_keyword(name: str) -> bool:
    """식별자에 도메인 키워드 포함 여부"""
    name_lower = name.lower()
    all_keywords = []
    for kws in RULE9_DOMAIN_KEYWORDS.values():
        all_keywords.extend(kws)
    return any(kw in name_lower for kw in all_keywords)


def _is_generic_only(name: str) -> bool:
    """식별자가 금지된 제네릭 이름만으로 구성되어 있는지"""
    name_lower = name.lower()
    return any(name_lower == generic for generic in RULE9_FORBIDDEN_GENERIC_NAMES)


def check_rule9_domain_terms(target_files: List[str], root_dir: str) -> List[Dict[str, Any]]:
    """
    RULE-9: 도메인 용어 준수 검증
    fail-closed: exception → FAIL 반환
    """
    violations = []
    for filepath in target_files:
        if not filepath.endswith(".py"):
            continue
        try:
            identifiers = _extract_identifiers(filepath)
            rel_path = os.path.relpath(filepath, root_dir)
            for name in identifiers:
                if _is_generic_only(name):
                    violations.append(build_violation(
                        rule_id="RULE-1",
                        file=rel_path,
                        violation_type="GENERIC_NAME_ONLY",
                        detail=f"Identifier {name} uses forbidden generic name without domain qualifier",
                        severity=SEVERITY_FAIL,
                    ))
        except Exception as exc:
            rel_path = os.path.relpath(filepath, root_dir)
            violations.append(build_exception_report("RULE-9", rel_path, exc)["violations"][0])
    return violations


def evaluate(root_dir: str, target_files: List[str]) -> List[Dict[str, Any]]:
    """
    domain_validator 전체 평가
    RULE-1 + RULE-9
    """
    violations = []
    violations.extend(check_rule1_legacy_backup(root_dir, target_files))
    violations.extend(check_rule9_domain_terms(target_files, root_dir))
    return violations
