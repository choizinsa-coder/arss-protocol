"""
static_scan.py
영역 3 — Static Safety Scan (코드 실행 없는 정적 검증)
EAG-S271-JENIVERIFY-001

제니 TRUST-ADVISORY ① 반영:
  Hermes 가동 전까지 외부 코드 유입 차단, 순수 Python 결정론적 한정.
  실제 코드를 실행하지 않고 ast 파싱 + 금지 패턴 스캔만 수행.

execution_sandbox(subprocess 실제 실행)는 2차 스코프 — 본 모듈에 없음.
"""

from __future__ import annotations

import ast

from .schemas import ScanResult, JVReason


# ── 금지 호출/임포트 (런타임 위험 행위) ──────────────────────────────────────
FORBIDDEN_CALLS = frozenset({
    "eval", "exec", "compile", "__import__",
})
FORBIDDEN_IMPORTS = frozenset({
    "os.system", "subprocess", "pty", "ctypes",
})
FORBIDDEN_ATTR_CALLS = frozenset({
    "system", "popen", "spawn", "fork", "Popen",
})


def syntax_check(source: str) -> ScanResult:
    """ast.parse 로 문법 검증 (실행하지 않음)."""
    try:
        ast.parse(source)
    except SyntaxError as e:
        return ScanResult(False, JVReason.SYNTAX_ERROR, f"line {e.lineno}: {e.msg}")
    return ScanResult(True, JVReason.OK)


def forbidden_pattern_scan(source: str) -> ScanResult:
    """ast 트리에서 위험 호출/임포트를 정적 탐지."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return ScanResult(False, JVReason.SYNTAX_ERROR, f"line {e.lineno}: {e.msg}")

    for node in ast.walk(tree):
        # 직접 호출: eval(), exec(), __import__()
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                return ScanResult(False, JVReason.FORBIDDEN_PATTERN, f"call:{func.id}")
            if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_ATTR_CALLS:
                return ScanResult(False, JVReason.FORBIDDEN_PATTERN, f"attr:{func.attr}")
        # import subprocess / import pty ...
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_IMPORTS or alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    return ScanResult(False, JVReason.FORBIDDEN_PATTERN, f"import:{alias.name}")
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in FORBIDDEN_IMPORTS or mod.split(".")[0] in FORBIDDEN_IMPORTS:
                return ScanResult(False, JVReason.FORBIDDEN_PATTERN, f"from:{mod}")

    return ScanResult(True, JVReason.OK)


def static_scan(source: str) -> ScanResult:
    """문법 + 금지 패턴 통합 정적 검증."""
    syn = syntax_check(source)
    if not syn.ok:
        return syn
    return forbidden_pattern_scan(source)
