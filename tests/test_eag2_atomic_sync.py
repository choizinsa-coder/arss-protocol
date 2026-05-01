"""
test_eag2_atomic_sync.py
========================
PT-S63-001 EAG-2 — atomic_sync 계층 분리 TC-AS-001~003
대상: index_validator가 atomic_sync를 호출하지 않음을 검증
EAG-2 APPROVED by 비오(Joshua) — S65
"""

import json
import os
import shutil
import tempfile
from unittest.mock import patch

import pytest

from tools.delta_context.index_validator import validate_index


def _make_delta(delta_id: str, seq: int, content_hash: str) -> dict:
    return {"delta_id": delta_id, "sequence_number": seq, "content_hash": content_hash}


def _setup(index_data: dict, domain_deltas: dict):
    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "INDEX.json")
    delta_root = os.path.join(tmpdir, "DELTA_LOG")
    os.makedirs(delta_root, exist_ok=True)

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f)

    for domain, deltas in domain_deltas.items():
        domain_dir = os.path.join(delta_root, domain)
        os.makedirs(domain_dir, exist_ok=True)
        for i, d in enumerate(deltas):
            with open(os.path.join(domain_dir, f"{i:04d}.json"), "w", encoding="utf-8") as f:
                json.dump(d, f)

    return tmpdir, index_path, delta_root


# ── TC-AS-001: index_validator가 atomic_sync를 import/호출하지 않음 ─────────────

def test_tc_as_001_no_atomic_sync_import():
    """index_validator 모듈이 atomic_sync를 실제 import하지 않음을 AST로 확인."""
    import ast
    import tools.delta_context.index_validator as iv_module
    source = open(iv_module.__file__.replace(".pyc", ".py").replace(
        "__pycache__/", "").replace(
        os.sep + "__pycache__" + os.sep, os.sep), "r", encoding="utf-8").read()

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            module = getattr(node, "module", "") or ""
            assert "atomic_sync" not in module, (
                "index_validator.py가 atomic_sync를 import하고 있음 — 계층 분리 위반"
            )
            for name in names:
                assert "atomic_sync" not in name, (
                    "index_validator.py가 atomic_sync를 import하고 있음 — 계층 분리 위반"
                )


# ── TC-AS-002: index_validator가 mutation_gate를 호출하지 않음 ─────────────────

def test_tc_as_002_no_mutation_gate_call():
    """index_validator 모듈이 mutation_gate를 실제 import하지 않음을 AST로 확인."""
    import ast
    import tools.delta_context.index_validator as iv_module
    source = open(iv_module.__file__.replace(".pyc", ".py").replace(
        "__pycache__/", "").replace(
        os.sep + "__pycache__" + os.sep, os.sep), "r", encoding="utf-8").read()

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            module = getattr(node, "module", "") or ""
            assert "mutation_gate" not in module, (
                "index_validator.py가 mutation_gate를 import하고 있음 — 계층 분리 위반"
            )
            for name in names:
                assert "mutation_gate" not in name, (
                    "index_validator.py가 mutation_gate를 import하고 있음 — 계층 분리 위반"
                )


# ── TC-AS-003: index_validator가 파일 write를 수행하지 않음 (READ-ONLY) ─────────

def test_tc_as_003_read_only_no_write():
    """validate_index() 실행 중 파일 write가 발생하지 않음을 확인."""
    deltas = [_make_delta("d-001", 1, "hash-aaa")]
    index = {"domains": {"config": {
        "latest_delta_id": "d-001",
        "latest_content_hash": "hash-aaa",
        "delta_count": 1,
    }}}
    tmpdir, ip, dr = _setup(index, {"config": deltas})

    write_calls = []

    original_open = open

    def mock_open(file, mode="r", *args, **kwargs):
        if "w" in str(mode) or "a" in str(mode):
            write_calls.append(file)
        return original_open(file, mode, *args, **kwargs)

    try:
        with patch("builtins.open", side_effect=mock_open):
            result = validate_index(ip, dr)
        assert result["result"] == "PASS"
        assert len(write_calls) == 0, (
            f"index_validator가 write를 시도함 (READ-ONLY 위반): {write_calls}"
        )
    finally:
        shutil.rmtree(tmpdir)
