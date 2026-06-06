"""
test_change_classifier.py
change_classifier.py v1.0.0 회귀 테스트

S196 오케스트레이션 Rev.2 — broad scope git diff 강제 검증기 테스트.
RULE-8 준수: placeholder 금지, 실제 failure-path 검증 포함.
"""

import os
import sys

import pytest

_EXEC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "exec_runtime",
)
if _EXEC_DIR not in sys.path:
    sys.path.insert(0, _EXEC_DIR)

from change_classifier import (  # noqa: E402
    ChangeVerdict,
    classify,
    is_test_file,
    parse_git_diff,
)


# ── is_test_file ──────────────────────────────────────────────────────────────

def test_is_test_file_prefix():
    assert is_test_file("tests/test_foo.py") is True


def test_is_test_file_suffix():
    assert is_test_file("tests/foo_test.py") is True


def test_is_test_file_non_test():
    assert is_test_file("tools/core.py") is False


def test_is_test_file_nested_non_test():
    # test_ 가 경로 중간에 있으나 파일명이 아닌 경우
    assert is_test_file("tools/test_helpers/core.py") is False


# ── ALLOW 경로 ────────────────────────────────────────────────────────────────

def test_allow_single_assert_value_change():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "-    assert result == 41\n"
        "+    assert result == 42\n"
    )
    result = classify(diff)
    assert result.verdict == ChangeVerdict.ALLOW


def test_allow_string_assert_change():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        '-    assert msg == "old"\n'
        '+    assert msg == "new"\n'
    )
    assert classify(diff).verdict == ChangeVerdict.ALLOW


def test_allow_empty_diff():
    assert classify("").verdict == ChangeVerdict.ALLOW


def test_allow_multi_test_files():
    diff = (
        "diff --git a/tests/test_a.py b/tests/test_a.py\n"
        "--- a/tests/test_a.py\n"
        "+++ b/tests/test_a.py\n"
        "-    assert x == 1\n"
        "+    assert x == 2\n"
        "diff --git a/tests/test_b.py b/tests/test_b.py\n"
        "--- a/tests/test_b.py\n"
        "+++ b/tests/test_b.py\n"
        "-    assert y == 3\n"
        "+    assert y == 4\n"
    )
    assert classify(diff).verdict == ChangeVerdict.ALLOW


# ── TRIGGER_REPORT_WAIT 경로 (failure-path, RULE-8) ─────────────────────────

def test_block_non_test_file():
    diff = (
        "diff --git a/tools/core.py b/tools/core.py\n"
        "--- a/tools/core.py\n"
        "+++ b/tools/core.py\n"
        "-    assert x == 1\n"
        "+    assert x == 2\n"
    )
    result = classify(diff)
    assert result.verdict == ChangeVerdict.TRIGGER_REPORT_WAIT
    assert any("non-test file" in r for r in result.reasons)


def test_block_function_def_change():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "+    def helper():\n"
    )
    result = classify(diff)
    assert result.verdict == ChangeVerdict.TRIGGER_REPORT_WAIT
    assert any("function definition" in r for r in result.reasons)


def test_block_import_change():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "+import os\n"
    )
    result = classify(diff)
    assert result.verdict == ChangeVerdict.TRIGGER_REPORT_WAIT
    assert any("import" in r for r in result.reasons)


def test_block_from_import_change():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "+from os import path\n"
    )
    assert classify(diff).verdict == ChangeVerdict.TRIGGER_REPORT_WAIT


def test_block_class_change():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "+class TestThing:\n"
    )
    assert classify(diff).verdict == ChangeVerdict.TRIGGER_REPORT_WAIT


def test_block_decorator_change():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "+@pytest.fixture\n"
    )
    assert classify(diff).verdict == ChangeVerdict.TRIGGER_REPORT_WAIT


def test_block_new_file():
    diff = (
        "diff --git a/tests/test_new.py b/tests/test_new.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/tests/test_new.py\n"
        "+    assert 1 == 1\n"
    )
    result = classify(diff)
    assert result.verdict == ChangeVerdict.TRIGGER_REPORT_WAIT
    assert any("new file" in r for r in result.reasons)


def test_block_deleted_file():
    diff = (
        "diff --git a/tests/test_old.py b/tests/test_old.py\n"
        "deleted file mode 100644\n"
        "--- a/tests/test_old.py\n"
        "+++ /dev/null\n"
        "-    assert 1 == 1\n"
    )
    result = classify(diff)
    assert result.verdict == ChangeVerdict.TRIGGER_REPORT_WAIT
    assert any("deletion" in r for r in result.reasons)


def test_block_mixed_assert_and_logic():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "-    assert z == 1\n"
        "+    assert z == 2\n"
        "+    x = compute()\n"
    )
    result = classify(diff)
    assert result.verdict == ChangeVerdict.TRIGGER_REPORT_WAIT
    assert any("non-assert logic" in r for r in result.reasons)


def test_block_non_test_takes_priority_over_assert():
    # Safe Default: non-test 파일이면 assert여도 차단
    diff = (
        "diff --git a/src/module.py b/src/module.py\n"
        "--- a/src/module.py\n"
        "+++ b/src/module.py\n"
        "-    assert config == 1\n"
        "+    assert config == 2\n"
    )
    assert classify(diff).verdict == ChangeVerdict.TRIGGER_REPORT_WAIT


# ── parse_git_diff 단위 ───────────────────────────────────────────────────────

def test_parse_extracts_file_path():
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "+    assert x == 1\n"
    )
    files = parse_git_diff(diff)
    assert len(files) == 1
    assert files[0].path == "tests/test_x.py"
    assert files[0].is_test_file is True


def test_parse_comment_lines_ignored():
    # 주석/공백 변경만 있으면 ALLOW
    diff = (
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "+    # updated comment\n"
    )
    assert classify(diff).verdict == ChangeVerdict.ALLOW
