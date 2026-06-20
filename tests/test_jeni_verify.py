"""
test_jeni_verify.py
영역 3 Jeni Dual Verification (J2-3) 검증 — TC-01 ~ TC-10
EAG-S271-JENIVERIFY-001 / 1차 스코프

execution_sandbox 미포함. 전부 결정론적.
"""

from tools.aics.aics_runtime import AICSRuntime
from tools.jeni_verify.static_scan import static_scan, syntax_check
from tools.jeni_verify.certificate import CertificateAuthority
from tools.jeni_verify.dual_verifier import DualVerifier
from tools.jeni_verify.metrics import MetricsCollector
from tools.jeni_verify.schemas import DualResult, JVReason, sha256_hex


SESSION = 271
CHAIN_TIP = "4bf0554"
SANDBOX_PATH = "/opt/arss/engine/arss-protocol/tools/sandbox/task-271-001-domi-design.md"

GOOD_SOURCE = "def add(a, b):\n    return a + b\n"
SYNTAX_BAD = "def broken(:\n    pass\n"
FORBIDDEN_SOURCE = "import os\nos.system('rm -rf /')\n"


def _aics(tmp_path):
    return AICSRuntime(
        active_tokens_path=str(tmp_path / "active_tokens.json"),
        identity_registry_path=str(tmp_path / "identity_registry.json"),
        safe_mode_flag_path=str(tmp_path / "safe_mode.flag"),
    )


# ── TC-01: 정상 ───────────────────────────────────────────────────────────
def test_tc01_valid_passes(tmp_path):
    aics = _aics(tmp_path)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    dv = DualVerifier(aics_runtime=aics)
    res = dv.verify(GOOD_SOURCE, "task-271-001-domi-design.md", SANDBOX_PATH,
                    token_id=tok.token_id, actor_id="domi",
                    session=SESSION, chain_tip=CHAIN_TIP)
    assert res.passed is True
    assert res.reason == JVReason.OK


# ── TC-02: syntax error ───────────────────────────────────────────────────
def test_tc02_syntax_error_fails(tmp_path):
    dv = DualVerifier()
    res = dv.verify(SYNTAX_BAD, "x.md", SANDBOX_PATH)
    assert res.technical_match is False
    assert res.reason == JVReason.TECHNICAL_FAIL


# ── TC-03: forbidden extension ────────────────────────────────────────────
def test_tc03_forbidden_extension_fails(tmp_path):
    dv = DualVerifier()
    res = dv.verify(GOOD_SOURCE, "malware.sh", SANDBOX_PATH)
    assert res.governance_align is False
    assert res.reason == JVReason.GOVERNANCE_FAIL
    assert res.detail == JVReason.FORBIDDEN_EXTENSION


# ── TC-04: sandbox path 탈출 ──────────────────────────────────────────────
def test_tc04_path_escape_fails(tmp_path):
    dv = DualVerifier()
    res = dv.verify(GOOD_SOURCE, "x.md", "/etc/passwd")
    assert res.governance_align is False
    assert res.detail == JVReason.PATH_ESCAPE


# ── TC-05: certificate hash mismatch ──────────────────────────────────────
def test_tc05_certificate_hash_mismatch(tmp_path):
    ca = CertificateAuthority(persist_dir=str(tmp_path / "certs"))
    cert = ca.issue(GOOD_SOURCE, True, True, test_passed=12, test_failed=0)
    # 정상 대조
    assert ca.verify(GOOD_SOURCE, cert) is True
    # 파일 변조 후 대조 → 불일치
    tampered = GOOD_SOURCE + "# injected\n"
    assert ca.verify(tampered, cert) is False
    assert ca.verify_reason(tampered, cert) == JVReason.CERTIFICATE_INVALID


# ── TC-06: expired/invalid AICS token ─────────────────────────────────────
def test_tc06_invalid_token_fails(tmp_path):
    aics = _aics(tmp_path)
    dv = DualVerifier(aics_runtime=aics)
    res = dv.verify(GOOD_SOURCE, "task-271-001-domi-design.md", SANDBOX_PATH,
                    token_id="nonexistent", actor_id="domi",
                    session=SESSION, chain_tip=CHAIN_TIP)
    assert res.governance_align is False
    assert res.detail == JVReason.TOKEN_INVALID


# ── TC-07: forbidden pattern (cross-sign tamper 대체: 위험 코드) ──────────
def test_tc07_forbidden_pattern_fails(tmp_path):
    dv = DualVerifier()
    res = dv.verify(FORBIDDEN_SOURCE, "x.md", SANDBOX_PATH)
    assert res.technical_match is False
    assert res.reason == JVReason.TECHNICAL_FAIL
    assert res.detail == JVReason.FORBIDDEN_PATTERN
    # static_scan 자체는 위험 패턴 상세를 반환 (import:os 또는 attr:system)
    scan = static_scan(FORBIDDEN_SOURCE)
    assert scan.ok is False
    assert ("os" in scan.detail) or ("system" in scan.detail)


# ── TC-08: SAFE_PASS / path 격리 위반 ─────────────────────────────────────
def test_tc08_safe_pass_path_violation(tmp_path):
    dv = DualVerifier()
    # tmp 경로(sandbox 밖) → path escape
    res = dv.verify(GOOD_SOURCE, "x.md", "/opt/arss/engine/arss-protocol/tools/tmp/x.md")
    assert res.governance_align is False


# ── TC-09: technical=true, governance=false ───────────────────────────────
def test_tc09_tech_pass_gov_fail(tmp_path):
    dv = DualVerifier()
    res = dv.verify(GOOD_SOURCE, "bad.exe", SANDBOX_PATH)
    assert res.technical_match is True
    assert res.governance_align is False
    assert res.passed is False


# ── TC-10: technical=false, governance=true ───────────────────────────────
def test_tc10_tech_fail_gov_pass(tmp_path):
    dv = DualVerifier()
    res = dv.verify(SYNTAX_BAD, "ok.md", SANDBOX_PATH)
    assert res.technical_match is False
    assert res.governance_align is True
    assert res.passed is False


# ── 지표 1 Primary 집계 ───────────────────────────────────────────────────
def test_metrics_primary_rate(tmp_path):
    mc = MetricsCollector()
    mc.record(DualResult(True, True))    # combined pass
    mc.record(DualResult(True, False))   # tech only
    mc.record(DualResult(False, True))   # gov only
    mc.record(DualResult(True, True))    # combined pass
    snap = mc.snapshot()
    assert snap.total_count == 4
    assert snap.technical_pass == 3
    assert snap.governance_pass == 3
    assert snap.combined_pass == 2
    assert snap.combined_rate == 0.5


def test_certificate_roundtrip(tmp_path):
    ca = CertificateAuthority(persist_dir=str(tmp_path / "certs"))
    cert = ca.issue("payload", True, True, test_passed=10, test_failed=0,
                    tx_id="BR-S271-001", domi_signature="d", jeni_signature="j")
    assert cert.sha256 == sha256_hex("payload")
    assert ca.verify("payload", cert) is True
