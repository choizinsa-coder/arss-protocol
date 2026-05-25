"""
test_runtime_generator.py
PT-S81-ARCH-001 Phase 2 — Step 2 pytest
RULE-3 이동: tools/session_context_gen/tests/ → tests/session_context_gen/ (S153)
"""
import json
import hashlib
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.session_context_gen.runtime_generator import (
    load_runtime, compute_content_hash,
    generate_runtime_meta, validate_runtime_integrity
)

VALID_RUNTIME = {
    '_zone': 'SESSION_STATE_RUNTIME',
    '_source_session': 82,
    'session_count': 82,
    'generated_at': '2026-05-05T00:00:00.000+09:00',
    'chain': {'tip': 'eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd'},
    'activation_allowed': False,
}

RUNTIME_WITH_BOOT_REF = {**VALID_RUNTIME, 'boot_hash': 'abc123'}
RUNTIME_WRONG_ZONE = {**VALID_RUNTIME, '_zone': 'SESSION_CONTEXT_FULL'}
RUNTIME_NO_CHAIN = {**VALID_RUNTIME, 'chain': {}}
RUNTIME_NO_SESSION = {k: v for k, v in VALID_RUNTIME.items() if k != 'session_count'}


def mock_runtime(data):
    return patch('tools.session_context_gen.runtime_generator.load_runtime', return_value=data)


# TC-1: 정상 RUNTIME → validate PASS
def test_tc1_valid_runtime_pass():
    with mock_runtime(VALID_RUNTIME):
        result = validate_runtime_integrity()
    assert result['status'] == 'PASS'
    assert result['checks']['zone_correct'] is True
    assert result['checks']['no_boot_reference'] is True
    assert result['checks']['chain_tip_present'] is True

# TC-2: boot_hash 역참조 존재 → FAIL
def test_tc2_boot_reference_fail():
    with mock_runtime(RUNTIME_WITH_BOOT_REF):
        result = validate_runtime_integrity()
    assert result['status'] == 'FAIL'
    assert result['checks']['no_boot_reference'] is False

# TC-3: zone 불일치 → FAIL
def test_tc3_wrong_zone_fail():
    with mock_runtime(RUNTIME_WRONG_ZONE):
        result = validate_runtime_integrity()
    assert result['status'] == 'FAIL'
    assert result['checks']['zone_correct'] is False

# TC-4: chain_tip 없음 → FAIL
def test_tc4_no_chain_tip_fail():
    with mock_runtime(RUNTIME_NO_CHAIN):
        result = validate_runtime_integrity()
    assert result['status'] == 'FAIL'
    assert result['checks']['chain_tip_present'] is False

# TC-5: session_count 없음 → FAIL
def test_tc5_no_session_count_fail():
    with mock_runtime(RUNTIME_NO_SESSION):
        result = validate_runtime_integrity()
    assert result['status'] == 'FAIL'
    assert result['checks']['session_count_present'] is False

# TC-6: content_hash 결정론적 검증
def test_tc6_content_hash_deterministic():
    h1 = compute_content_hash(VALID_RUNTIME)
    h2 = compute_content_hash(VALID_RUNTIME)
    assert h1 == h2
    assert len(h1) == 64

# TC-7: generate_runtime_meta 반환값 구조 확인
def test_tc7_meta_structure():
    with mock_runtime(VALID_RUNTIME):
        meta = generate_runtime_meta()
    assert 'runtime_content_hash' in meta
    assert 'session_count' in meta
    assert 'chain_tip' in meta
    assert 'zone' in meta
    assert 'boot_hash' not in meta
    assert 'boot_ref' not in meta
    assert 'boot_pair_hash' not in meta

# TC-8: boot_hash 역참조 시 generate_runtime_meta ValueError
def test_tc8_meta_boot_reference_raises():
    with mock_runtime(RUNTIME_WITH_BOOT_REF):
        with pytest.raises(ValueError, match='forbidden'):
            generate_runtime_meta()

# TC-9: 파일 미존재 → FAIL
def test_tc9_file_not_found():
    result = validate_runtime_integrity(Path('/nonexistent/path.json'))
    assert result['status'] == 'FAIL'
    assert result['checks']['file_exists'] is False

# TC-10: chain_tip이 Step1 기준값과 일치
def test_tc10_chain_tip_matches_baseline():
    with mock_runtime(VALID_RUNTIME):
        meta = generate_runtime_meta()
    assert meta['chain_tip'] == 'eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd'
