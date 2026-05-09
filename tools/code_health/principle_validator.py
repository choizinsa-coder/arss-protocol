"""
principle_validator.py — Code Health Enforcement Layer v1.0
AIBA Code Health Protocol
CODING_PRINCIPLE.md 규칙 검증 모듈 (RULE-2~8)
"""

import ast
import os
from typing import List, Dict, Any, Optional

from tools.code_health.rule_loader import (
    RULE2_REQUIRED_PREFIX,
    RULE2_BARE_IMPORT_TARGETS,
    RULE3_CANONICAL_TEST_ROOT,
    RULE4_ACTIVE_VERSION_MARKERS,
    RULE4_INACTIVE_MARKERS,
    RULE5_FUNCTION_LINE_FAIL,
    RULE5_FUNCTION_LINE_REVIEW,
    RULE6_FORBIDDEN_EXCEPT_PATTERNS,
    RULE7_MUTATION_KEYWORDS,
    RULE7_READONLY_PREFIXES,
    RULE7_STATE_TARGETS,
    RULE7_CONSTRUCTOR_EXCEPTION,
    RULE8_TEST_FILE_PREFIX,
    SEVERITY_FAIL,
    SEVERITY_REVIEW,
)
from tools.code_health.violation_report import build_violation, build_exception_report


# ─── RULE-2: Import 경로 표준화 ───────────────────────────────────────────────

def _get_imports(tree: ast.AST) -> List[ast.stmt]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]


def check_rule2_imports(filepath: str, root_dir: str) -> List[Dict[str, Any]]:
    """bare import 및 tools.* 미준수 탐지 — fail-closed"""
    violations = []
    rel_path = os.path.relpath(filepath, root_dir)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
        for node in _get_imports(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in RULE2_BARE_IMPORT_TARGETS:
                        violations.append(build_violation(
                            rule_id="RULE-2",
                            file=rel_path,
                            violation_type="BARE_IMPORT",
                            detail=f"Bare import detected: 'import {alias.name}'",
                            severity=SEVERITY_FAIL,
                        ))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                module = node.module or ""
                if module in RULE2_BARE_IMPORT_TARGETS:
                    violations.append(build_violation(
                        rule_id="RULE-2",
                        file=rel_path,
                        violation_type="BARE_IMPORT",
                        detail=f"Bare import detected: 'from {module} import ...'",
                        severity=SEVERITY_FAIL,
                    ))
                if module.startswith("delta_context") or module.startswith("auto_loader"):
                    violations.append(build_violation(
                        rule_id="RULE-2",
                        file=rel_path,
                        violation_type="IMPORT_PATH_NOT_STANDARD",
                        detail=f"Import '{module}' must use 'tools.{module}' absolute path",
                        severity=SEVERITY_FAIL,
                    ))
    except Exception as exc:
        violations.append(build_exception_report("RULE-2", rel_path, exc)["violations"][0])
    return violations


# ─── RULE-3: Test 위치 표준화 ─────────────────────────────────────────────────

def check_rule3_test_location(target_files: List[str], root_dir: str) -> List[Dict[str, Any]]:
    """신규 test 파일이 canonical root 외부에 있는지 탐지"""
    violations = []
    canonical_root = os.path.join(root_dir, RULE3_CANONICAL_TEST_ROOT)
    try:
        for filepath in target_files:
            filename = os.path.basename(filepath)
            if filename.startswith(RULE8_TEST_FILE_PREFIX) and filename.endswith(".py"):
                if not filepath.startswith(canonical_root):
                    rel_path = os.path.relpath(filepath, root_dir)
                    violations.append(build_violation(
                        rule_id="RULE-3",
                        file=rel_path,
                        violation_type="TEST_LOCATION_VIOLATION",
                        detail=f"Test file outside canonical root '{RULE3_CANONICAL_TEST_ROOT}/'",
                        severity=SEVERITY_FAIL,
                    ))
    except Exception as exc:
        violations.append(build_exception_report("RULE-3", root_dir, exc)["violations"][0])
    return violations


# ─── RULE-4: Active/Inactive 버전 분리 ───────────────────────────────────────

def check_rule4_version_declaration(root_dir: str) -> List[Dict[str, Any]]:
    """eps_v1_3_d / eps_v1_4 공존 등 버전 공존 탐지"""
    violations = []
    try:
        tools_dir = os.path.join(root_dir, "tools")
        if not os.path.isdir(tools_dir):
            return violations
        subdirs = [d for d in os.listdir(tools_dir) if os.path.isdir(os.path.join(tools_dir, d))]
        base_names: Dict[str, List[str]] = {}
        for d in subdirs:
            base = d.split("_v")[0] if "_v" in d else d
            base_names.setdefault(base, []).append(d)
        for base, versions in base_names.items():
            if len(versions) > 1:
                has_marker = any(
                    os.path.exists(os.path.join(tools_dir, v, marker))
                    for v in versions
                    for marker in RULE4_ACTIVE_VERSION_MARKERS
                )
                if not has_marker:
                    violations.append(build_violation(
                        rule_id="RULE-4",
                        file="tools/",
                        violation_type="ACTIVE_VERSION_NOT_DECLARED",
                        detail=f"Multiple versions coexist without ACTIVE_VERSION: {versions}",
                        severity=SEVERITY_FAIL,
                    ))
    except Exception as exc:
        violations.append(build_exception_report("RULE-4", root_dir, exc)["violations"][0])
    return violations


# ─── RULE-5: 함수 책임 한계 ──────────────────────────────────────────────────

def check_rule5_function_size(filepath: str, root_dir: str) -> List[Dict[str, Any]]:
    """함수 라인 수 초과 탐지 — fail-closed"""
    violations = []
    rel_path = os.path.relpath(filepath, root_dir)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno and node.lineno:
                    line_count = node.end_lineno - node.lineno + 1
                    if line_count > RULE5_FUNCTION_LINE_FAIL:
                        violations.append(build_violation(
                            rule_id="RULE-5",
                            file=rel_path,
                            violation_type="FUNCTION_TOO_LONG",
                            detail=f"Function '{node.name}' is {line_count} lines (FAIL threshold: {RULE5_FUNCTION_LINE_FAIL})",
                            severity=SEVERITY_FAIL,
                        ))
                    elif line_count > RULE5_FUNCTION_LINE_REVIEW:
                        violations.append(build_violation(
                            rule_id="RULE-5",
                            file=rel_path,
                            violation_type="FUNCTION_LENGTH_REVIEW",
                            detail=f"Function '{node.name}' is {line_count} lines (REVIEW threshold: {RULE5_FUNCTION_LINE_REVIEW})",
                            severity=SEVERITY_REVIEW,
                        ))
    except Exception as exc:
        violations.append(build_exception_report("RULE-5", rel_path, exc)["violations"][0])
    return violations


# ─── RULE-6: Fail-Closed 예외 처리 ───────────────────────────────────────────

def check_rule6_fail_closed(filepath: str, root_dir: str) -> List[Dict[str, Any]]:
    """except: pass / continue / success 반환 탐지 — fail-closed"""
    violations = []
    rel_path = os.path.relpath(filepath, root_dir)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                for child in ast.walk(node):
                    if isinstance(child, ast.Pass):
                        violations.append(build_violation(
                            rule_id="RULE-6",
                            file=rel_path,
                            violation_type="EXCEPT_PASS",
                            detail="'except: pass' pattern detected — fail-closed violation",
                            severity=SEVERITY_FAIL,
                        ))
                    elif isinstance(child, ast.Continue):
                        violations.append(build_violation(
                            rule_id="RULE-6",
                            file=rel_path,
                            violation_type="EXCEPT_CONTINUE",
                            detail="'except: continue' pattern detected — fail-closed violation",
                            severity=SEVERITY_FAIL,
                        ))
    except Exception as exc:
        violations.append(build_exception_report("RULE-6", rel_path, exc)["violations"][0])
    return violations


# ─── RULE-7: 상태 변경 명시성 ────────────────────────────────────────────────
RULE7_MUTATION_METHODS = {"update", "append", "extend", "insert", "remove", "pop", "clear", "add", "discard", "setdefault"}

def _has_state_mutation_ast(node, state_targets):
    """AST 기준 실제 state 변경 노드 감지 (Assign계열 + 메서드 호출)"""
    for child in ast.walk(node):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                t = ast.unparse(target).lower()
                if any(s.lower() in t for s in state_targets):
                    return True
        elif isinstance(child, (ast.AugAssign, ast.AnnAssign)):
            if child.value is not None or isinstance(child, ast.AugAssign):
                t = ast.unparse(child.target).lower()
                if any(s.lower() in t for s in state_targets):
                    return True
        elif isinstance(child, ast.Call):
            if isinstance(child.func, ast.Attribute):
                method = child.func.attr.lower()
                obj = ast.unparse(child.func.value).lower()
                if method in RULE7_MUTATION_METHODS:
                    if any(s.lower() in obj for s in state_targets):
                        return True
    return False

def check_rule7_mutation_explicitness(filepath: str, root_dir: str) -> List[Dict[str, Any]]:
    """state 변경 함수에 mutation 키워드 없는 경우 탐지 — fail-closed"""
    violations = []
    rel_path = os.path.relpath(filepath, root_dir)
    if "/tests/" in rel_path.replace(os.sep, "/"):
        return violations
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in RULE7_CONSTRUCTOR_EXCEPTION:
                continue
            has_readonly_prefix = any(node.name.lower().startswith(p) for p in RULE7_READONLY_PREFIXES)
            if has_readonly_prefix:
                continue
            has_mutation_keyword = any(kw in node.name.lower() for kw in RULE7_MUTATION_KEYWORDS)
            func_source = ast.unparse(node) if hasattr(ast, "unparse") else ""
            touches_state = any(t in func_source for t in RULE7_STATE_TARGETS)
            actual_mutation = _has_state_mutation_ast(node, RULE7_STATE_TARGETS)
            if has_mutation_keyword and touches_state:
                continue
            if actual_mutation and not has_mutation_keyword:
                violations.append(build_violation(
                    rule_id="RULE-7",
                    file=rel_path,
                    violation_type="HIDDEN_STATE_MUTATION",
                    detail=f"Function '{node.name}' mutates state without mutation-signaling name",
                    severity=SEVERITY_FAIL,
                ))
            elif touches_state and not actual_mutation and not has_mutation_keyword:
                violations.append(build_violation(
                    rule_id="RULE-7",
                    file=rel_path,
                    violation_type="HIDDEN_STATE_MUTATION_REVIEW",
                    detail=f"Function '{node.name}' touches state — review required (unclear mutation intent)",
                    severity=SEVERITY_REVIEW,
                ))
    except Exception as exc:
        violations.append(build_exception_report("RULE-7", rel_path, exc)["violations"][0])
    return violations

# ─── RULE-8: TDD Gate ────────────────────────────────────────────────────────

def check_rule8_tdd_gate(target_files: List[str], root_dir: str) -> List[Dict[str, Any]]:
    """변경 파일에 대응 test 파일 존재 여부 탐지"""
    violations = []
    test_root = os.path.join(root_dir, RULE3_CANONICAL_TEST_ROOT)
    try:
        runtime_files = [
            f for f in target_files
            if f.endswith(".py") and not os.path.basename(f).startswith(RULE8_TEST_FILE_PREFIX)
        ]
        for filepath in runtime_files:
            basename = os.path.basename(filepath).replace(".py", "")
            expected_test = os.path.join(test_root, f"test_{basename}.py")
            if not os.path.exists(expected_test):
                rel_path = os.path.relpath(filepath, root_dir)
                violations.append(build_violation(
                    rule_id="RULE-8",
                    file=rel_path,
                    violation_type="MISSING_TEST_MAPPING",
                    detail=f"No test file found for '{basename}' (expected: tests/test_{basename}.py)",
                    severity=SEVERITY_FAIL,
                ))
    except Exception as exc:
        violations.append(build_exception_report("RULE-8", root_dir, exc)["violations"][0])
    return violations


# ─── 전체 평가 ────────────────────────────────────────────────────────────────

def evaluate(root_dir: str, target_files: List[str]) -> List[Dict[str, Any]]:
    """
    principle_validator 전체 평가
    RULE-2~8
    """
    violations = []
    py_files = [f for f in target_files if f.endswith(".py")]

    violations.extend(check_rule4_version_declaration(root_dir))
    violations.extend(check_rule3_test_location(target_files, root_dir))
    violations.extend(check_rule8_tdd_gate(target_files, root_dir))

    for filepath in py_files:
        if not os.path.exists(filepath):
            continue
        violations.extend(check_rule2_imports(filepath, root_dir))
        violations.extend(check_rule5_function_size(filepath, root_dir))
        violations.extend(check_rule6_fail_closed(filepath, root_dir))
        violations.extend(check_rule7_mutation_explicitness(filepath, root_dir))

    return violations


# ─── CLI 진입점 ───────────────────────────────────────────────────────────────

EXCLUDE_DIRS = {"venv", "tests", "99_LEGACY", "__pycache__", ".git"}

def _collect_files(root_dir: str) -> List[str]:
    """venv/, tests/, 99_LEGACY/ 제외한 .py 파일 수집"""
    collected = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for filename in filenames:
            if filename.endswith(".py"):
                collected.append(os.path.join(dirpath, filename))
    return collected


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="AIBA Code Health Principle Validator")
    parser.add_argument("--rule", type=int, default=0, help="Rule number to check (2-8). 0 = all rules.")
    parser.add_argument("--root", type=str, default=os.getcwd(), help="Root directory to scan.")
    args = parser.parse_args()

    root_dir = os.path.abspath(args.root)
    target_files = _collect_files(root_dir)

    all_violations = evaluate(root_dir, target_files)

    if args.rule != 0:
        rule_key = f"RULE-{args.rule}"
        all_violations = [v for v in all_violations if v.get("rule_id") == rule_key]

    fail_count = sum(1 for v in all_violations if v.get("severity") == SEVERITY_FAIL)
    review_count = sum(1 for v in all_violations if v.get("severity") == SEVERITY_REVIEW)

    for v in all_violations:
        print(f"[{v.get('severity')}] {v.get('rule_id')} | {v.get('file')} | {v.get('type')} | {v.get('detail')}")

    print(f"\n=== SUMMARY === FAIL: {fail_count} / REVIEW: {review_count} / TOTAL: {len(all_violations)}")
