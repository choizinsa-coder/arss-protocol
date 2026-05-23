"""
test_mcp_read_server.py
PT-S134-VPS-OBS-001 Phase 1 READ ONLY OBSERVABILITY
pytest 테스트

S145 수정: PT-S143-TEST-DEBT-001 Group A/B 수습
  - sys.modules module-level 주입 → pytest fixture(scope='module') 전환
    근거: collection-time 주입이 test_mcp_hard_containment::test_ht6 /
          test_mcp_server_poc / phase_b / phase_c 오염
    patch.dict 사용으로 fixture 종료 시 sys.modules 자동 복원 보장
"""

import os
import sys
import time
import hmac
import hashlib
import importlib
import tempfile
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import unittest.mock as mock

sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "mcp"))

import mcp_read_server  # collection-time: real module (fixture 전 상태)

from mcp_read_server import (
    ReadOnlyServer,
    DenyResult,
    _validate_path,
    _validate_purpose,
    ALLOWED_PURPOSES,
    FORBIDDEN_PURPOSES,
    CODE_ROOT,
    GOVERNANCE_ROOT,
    EVIDENCE_ROOT,
    LOG_ROOT,
    METADATA_ROOT,
    ALLOWED_SERVICES,
)

server = ReadOnlyServer()

# ── module-scope autouse fixture: sys.modules 격리 ───────────────────────────
# collection-time이 아닌 test execution-time에 mock 주입 → 후속 파일 오염 방지.
# patch.dict: fixture 종료 시 sys.modules 자동 복원.
# reload: mcp_read_server가 mock mcp_audit_broker를 사용하도록 갱신.

@pytest.fixture(autouse=True, scope='module')
def _mock_audit_broker():
    """
    sys.modules 격리 전용 (reload 없음) — collection-time 오염 방지.
    reload 제거 이유: reload 시 DenyResult 클래스 객체 교체 →
      모듈 레벨 바인딩(OLD)과 _validate_purpose raise 대상(NEW) 불일치 →
      pytest.raises(DenyResult) 실패.
    mcp_read_server는 collection-time에 real audit_broker로 로드.
    server method 테스트는 real audit_broker로 정상 동작 확인됨.
    patch.dict: fixture 종료 시 sys.modules 자동 복원 → poc/phase_b/c 격리 ✓
    """
    _audit_mock = mock.MagicMock()
    _audit_mock.write_audit = mock.MagicMock()

    with patch.dict(sys.modules, {'mcp_audit_broker': _audit_mock}):
        yield
    # with 블록 종료: sys.modules 자동 복원 (patch.dict 보장)


# ── 헬퍼 ──────────────────────────────────────────────────────────
SECRET = "test-hmac-secret-s134"

def make_hmac(actor_id, connector, nonce, ts, payload):
    return hmac.new(
        SECRET.encode(),
        f"{actor_id}:{connector}:{nonce}:{ts}:{payload}".encode(),
        hashlib.sha256,
    ).hexdigest()

def base_kwargs(actor_id="caddy", payload="test", extra_nonce=""):
    ts = time.time()
    nonce = f"nonce-{ts}{extra_nonce}"
    connector = "claude.ai-arss-protocol"
    h = make_hmac(actor_id, connector, nonce, ts, payload)
    return dict(
        actor_id=actor_id,
        connector_identity=connector,
        hmac_value=h,
        nonce=nonce,
        timestamp=ts,
        hmac_secret=SECRET,
        purpose="OBSERVATION",
    )


# ── TC-1: Purpose 허용 ─────────────────────────────────────────────
def test_tc1_allowed_purpose():
    for p in ALLOWED_PURPOSES:
        _validate_purpose(p)  # 예외 없어야 함

# ── TC-2: Purpose 금지 ─────────────────────────────────────────────
def test_tc2_forbidden_purpose():
    for p in FORBIDDEN_PURPOSES:
        with pytest.raises(DenyResult) as exc:
            _validate_purpose(p)
        assert "FORBIDDEN_PURPOSE" in exc.value.reason

# ── TC-3: unknown purpose 거부 ─────────────────────────────────────
def test_tc3_unknown_purpose():
    with pytest.raises(DenyResult) as exc:
        _validate_purpose("HACK_THE_PLANET")
    assert "UNKNOWN_PURPOSE" in exc.value.reason

# ── TC-4: unknown actor 거부 ──────────────────────────────────────
def test_tc4_unknown_actor(tmp_path):
    kwargs = base_kwargs()
    kwargs['actor_id'] = "unknown_agent"
    ts = kwargs['timestamp']
    nonce = kwargs['nonce']
    kwargs['hmac_value'] = make_hmac("unknown_agent", kwargs['connector_identity'],
                                      nonce, ts, str(tmp_path))
    result = server.read_file(str(tmp_path), **kwargs)
    assert result['status'] == 'DENY'
    assert 'UNKNOWN_ACTOR' in result['reason']

# ── TC-5: unknown connector 거부 ──────────────────────────────────
def test_tc5_unknown_connector(tmp_path):
    kwargs = base_kwargs()
    kwargs['connector_identity'] = "evil-connector"
    ts = kwargs['timestamp']
    nonce = kwargs['nonce']
    kwargs['hmac_value'] = make_hmac("caddy", "evil-connector", nonce, ts, str(tmp_path))
    result = server.read_file(str(tmp_path), **kwargs)
    assert result['status'] == 'DENY'
    assert 'UNKNOWN_CLIENT' in result['reason']

# ── TC-6: stale timestamp 거부 ────────────────────────────────────
def test_tc6_stale_timestamp(tmp_path):
    stale_ts = time.time() - 400  # 400초 전
    nonce = f"nonce-stale-{stale_ts}"
    connector = "claude.ai-arss-protocol"
    h = make_hmac("caddy", connector, nonce, stale_ts, str(tmp_path))
    result = server.read_file(
        str(tmp_path), actor_id="caddy", connector_identity=connector,
        hmac_value=h, nonce=nonce, timestamp=stale_ts,
        hmac_secret=SECRET, purpose="OBSERVATION",
    )
    assert result['status'] == 'DENY'
    assert 'STALE_TIMESTAMP' in result['reason']

# ── TC-7: nonce replay 거부 ───────────────────────────────────────
def test_tc7_nonce_replay(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")

    with patch('mcp_read_server.CODE_ROOT', tmp_path), \
         patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'caddy': [tmp_path]}):
        kwargs1 = base_kwargs(payload=str(test_file), extra_nonce="-replay-test")
        r1 = server.read_file(str(test_file), **kwargs1)
        r2 = server.read_file(str(test_file), **kwargs1)
        assert r2['status'] == 'DENY'
        assert 'NONCE_REPLAY' in r2['reason']

# ── TC-8: HMAC 위조 거부 ─────────────────────────────────────────
def test_tc8_hmac_mismatch(tmp_path):
    kwargs = base_kwargs(payload=str(tmp_path))
    kwargs['hmac_value'] = "deadbeef" * 8  # 위조
    result = server.read_file(str(tmp_path), **kwargs)
    assert result['status'] == 'DENY'
    assert 'AUTH_MISMATCH' in result['reason']

# ── TC-9: forbidden path pattern 거부 ────────────────────────────
def test_tc9_forbidden_path(tmp_path):
    secret_file = tmp_path / ".env"
    secret_file.write_text("SECRET=abc")
    with patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'caddy': [tmp_path]}):
        kwargs = base_kwargs(payload=str(secret_file))
        result = server.read_file(str(secret_file), **kwargs)
    assert result['status'] == 'DENY'
    assert 'FORBIDDEN_PATH_PATTERN' in result['reason']

# ── TC-10: path not in whitelist 거부 ────────────────────────────
def test_tc10_path_not_in_whitelist():
    kwargs = base_kwargs(payload="/etc/passwd")
    result = server.read_file("/etc/passwd", **kwargs)
    assert result['status'] == 'DENY'
    assert 'PATH_NOT_IN_WHITELIST' in result['reason']

# ── TC-11: read_file 정상 동작 ────────────────────────────────────
def test_tc11_read_file_allow(tmp_path):
    test_file = tmp_path / "code.py"
    test_file.write_text("print('hello')")
    with patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'caddy': [tmp_path]}):
        kwargs = base_kwargs(payload=str(test_file), extra_nonce="-tc11")
        result = server.read_file(str(test_file), **kwargs)
    assert result['status'] == 'ALLOW'
    assert "print('hello')" in result['content']

# ── TC-12: list_dir 정상 동작 ────────────────────────────────────
def test_tc12_list_dir_allow(tmp_path):
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    with patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'caddy': [tmp_path]}):
        kwargs = base_kwargs(payload=str(tmp_path), extra_nonce="-tc12")
        result = server.list_dir(str(tmp_path), **kwargs)
    assert result['status'] == 'ALLOW'
    assert 'a.py' in result['entries']

# ── TC-13: check_service_state 허용 서비스 ───────────────────────
def test_tc13_service_not_in_allowlist():
    kwargs = base_kwargs(payload="sshd", extra_nonce="-tc13")
    result = server.check_service_state("sshd", **kwargs)
    assert result['status'] == 'DENY'
    assert 'SERVICE_NOT_IN_ALLOWLIST' in result['reason']

# ── TC-14: read_metadata 파일명 제한 ─────────────────────────────
def test_tc14_metadata_filename_restriction(tmp_path):
    bad_file = tmp_path / "random_data.json"
    bad_file.write_text("{}")
    with patch('mcp_read_server.METADATA_ROOT', tmp_path), \
         patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'caddy': [tmp_path]}):
        kwargs = base_kwargs(payload=str(bad_file), extra_nonce="-tc14")
        result = server.read_metadata(str(bad_file), **kwargs)
    assert result['status'] == 'DENY'
    assert 'METADATA_FILE_NOT_ALLOWED' in result['reason']

# ── TC-15: read_metadata SESSION_CONTEXT 허용 ────────────────────
def test_tc15_metadata_session_context_allow(tmp_path):
    sc_file = tmp_path / "SESSION_CONTEXT_S133_FINAL.json"
    sc_file.write_text('{"session": 133}')
    with patch('mcp_read_server.METADATA_ROOT', tmp_path), \
         patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'caddy': [tmp_path]}):
        kwargs = base_kwargs(payload=str(sc_file), extra_nonce="-tc15")
        result = server.read_metadata(str(sc_file), **kwargs)
    assert result['status'] == 'ALLOW'

# ── TC-16: audit bulk dump 제한 ──────────────────────────────────
def test_tc16_audit_bulk_limit(tmp_path):
    log_file = tmp_path / "audit.log"
    log_file.write_text("\n".join([f"event-{i}" for i in range(500)]))
    with patch('mcp_read_server.LOG_ROOT', tmp_path), \
         patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'caddy': [tmp_path]}):
        kwargs = base_kwargs(payload=str(log_file), extra_nonce="-tc16")
        result = server.read_audit_event(str(log_file), event_range=500, **kwargs)
    assert result['status'] == 'ALLOW'
    assert len(result['events']) <= 100  # bulk dump 제한

# ── TC-17: domi 허용 영역 검증 ───────────────────────────────────
def test_tc17_domi_code_root_allow(tmp_path):
    code_file = tmp_path / "design.py"
    code_file.write_text("# design")
    with patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'domi': [tmp_path]}):
        ts = time.time()
        nonce = f"nonce-domi-tc17-{ts}"
        connector = "claude.ai-arss-protocol"
        h = make_hmac("domi", connector, nonce, ts, str(code_file))
        result = server.read_file(
            str(code_file), actor_id="domi",
            connector_identity=connector, hmac_value=h,
            nonce=nonce, timestamp=ts, hmac_secret=SECRET, purpose="CONSISTENCY_CHECK",
        )
    assert result['status'] == 'ALLOW'

# ── TC-18: get_runtime_snapshot 허용 ─────────────────────────────
def test_tc18_runtime_snapshot(tmp_path):
    with patch('mcp_read_server.METADATA_ROOT', tmp_path), \
         patch('mcp_read_server.ALLOWED_SERVICES', set()):
        kwargs = base_kwargs(payload="runtime_snapshot", extra_nonce="-tc18")
        del kwargs['purpose']
        result = server.get_runtime_snapshot(purpose="OBSERVATION", **kwargs)
    assert result['status'] == 'ALLOW'
    assert 'snapshot' in result

# ── TC-19: JENI audit 허용 영역 ──────────────────────────────────
def test_tc19_jeni_log_root_allow(tmp_path):
    log_file = tmp_path / "audit.log"
    log_file.write_text("event1\nevent2")
    with patch('mcp_read_server.LOG_ROOT', tmp_path), \
         patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'jeni': [tmp_path]}):
        ts = time.time()
        nonce = f"nonce-jeni-tc19-{ts}"
        connector = "claude.ai-arss-protocol"
        h = make_hmac("jeni", connector, nonce, ts, str(log_file))
        result = server.read_audit_event(
            str(log_file), event_range=10,
            actor_id="jeni", connector_identity=connector,
            hmac_value=h, nonce=nonce, timestamp=ts,
            hmac_secret=SECRET, purpose="AUDIT_INSPECTION",
        )
    assert result['status'] == 'ALLOW'

# ── TC-20: grep_scoped depth 제한 ────────────────────────────────
def test_tc20_grep_scoped_allow(tmp_path):
    py_file = tmp_path / "module.py"
    py_file.write_text("def hello(): pass\n# target_string")
    with patch('mcp_read_server.CODE_ROOT', tmp_path), \
         patch('mcp_read_server.AGENT_ROOT_ALLOWLIST', {'caddy': [tmp_path]}):
        ts = time.time()
        nonce = f"nonce-grep-tc20-{ts}"
        connector = "claude.ai-arss-protocol"
        payload = f"{tmp_path}:target_string"
        h = make_hmac("caddy", connector, nonce, ts, payload)
        result = server.grep_scoped(
            str(tmp_path), "target_string",
            actor_id="caddy", connector_identity=connector,
            hmac_value=h, nonce=nonce, timestamp=ts,
            hmac_secret=SECRET, purpose="CONSISTENCY_CHECK",
        )
    assert result['status'] == 'ALLOW'
    assert len(result['matches']) >= 1
