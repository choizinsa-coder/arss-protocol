"""
test_verification_trace.py
Verification Trace 최소 스키마(Phase 1) 테스트.
EAG-S344-VERIFICATION-TRACE-P1-001
"""

import pytest

from tools.jeni_verify.verification_trace import (
    VerificationTraceRecord,
    TraceVerdict,
    create_trace_record,
    EVIDENCE_SNIPPET_MAX_LEN,
)
from tools.jeni_verify.schemas import sha256_hex


def test_tc1_basic_creation():
    rec = create_trace_record(
        assertion_id="RULE-TEST-001",
        evidence_source="/opt/arss/engine/arss-protocol/docs/example.md",
        evidence_snippet="example evidence text",
        verdict=TraceVerdict.PASS,
        verifier_agent="jeni",
    )
    assert rec.assertion_id == "RULE-TEST-001"
    assert rec.verifier_agent == "jeni"
    assert rec.verdict == "PASS"


def test_tc2_trace_id_is_unique():
    rec1 = create_trace_record("A", "src", "x", TraceVerdict.PASS, "jeni")
    rec2 = create_trace_record("A", "src", "x", TraceVerdict.PASS, "jeni")
    assert rec1.trace_id != rec2.trace_id
    assert rec1.trace_id.startswith("TRACE-")


def test_tc3_evidence_hash_auto_computed():
    snippet = "hello world"
    rec = create_trace_record("A", "src", snippet, TraceVerdict.PASS, "jeni")
    assert rec.evidence_hash == sha256_hex(snippet)


def test_tc4_snippet_over_limit_raises():
    long_snippet = "x" * (EVIDENCE_SNIPPET_MAX_LEN + 1)
    with pytest.raises(ValueError):
        create_trace_record("A", "src", long_snippet, TraceVerdict.PASS, "jeni")


def test_tc5_snippet_at_limit_ok():
    snippet = "x" * EVIDENCE_SNIPPET_MAX_LEN
    rec = create_trace_record("A", "src", snippet, TraceVerdict.PASS, "jeni")
    assert len(rec.evidence_snippet) == EVIDENCE_SNIPPET_MAX_LEN


def test_tc6_invalid_verdict_raises():
    with pytest.raises(ValueError):
        create_trace_record("A", "src", "x", "MAYBE", "jeni")


def test_tc7_all_verdict_values_accepted():
    for v in (TraceVerdict.PASS, TraceVerdict.FAIL, TraceVerdict.INCONCLUSIVE):
        rec = create_trace_record("A", "src", "x", v, "jeni")
        assert rec.verdict == v


def test_tc8_to_dict_contains_all_fields():
    rec = create_trace_record("A", "src", "x", TraceVerdict.PASS, "jeni")
    d = rec.to_dict()
    for key in (
        "trace_id", "assertion_id", "evidence_source", "evidence_snippet",
        "evidence_hash", "verdict", "verifier_agent", "generated_at",
    ):
        assert key in d


def test_tc9_generated_at_is_iso_string():
    rec = create_trace_record("A", "src", "x", TraceVerdict.PASS, "jeni")
    assert "T" in rec.generated_at


def test_tc10_explicit_evidence_hash_preserved():
    rec = VerificationTraceRecord(
        assertion_id="A",
        evidence_source="src",
        evidence_snippet="x",
        verdict=TraceVerdict.PASS,
        verifier_agent="jeni",
        evidence_hash="deadbeef",
    )
    assert rec.evidence_hash == "deadbeef"
