"""
test_boot_generator_phase2.py
PT-S81-ARCH-001 Phase 2 — Step 4 pytest
boot_generator.py runtime_pair_hash 연동 검증
RULE-3 이동: tools/session_context_gen/tests/ → tests/session_context_gen/ (S153)
"""
import json, hashlib, pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.session_context_gen.boot_generator import generate

ARSS_ROOT = Path('/opt/arss/engine/arss-protocol')
FULL_PATH = str(ARSS_ROOT / 'SESSION_CONTEXT_FULL.json')
BOOT_PATH = str(ARSS_ROOT / 'SESSION_BOOT.json')

MOCK_HASH = 'dccec82e2b4e2a868a2688d0955d1d842610e70e95b03aa4a04e9cb41ef18e80'

# TC-1: runtime_pair_hash 미전달 시 빈 문자열로 기본값 처리
def test_tc1_default_runtime_pair_hash(tmp_path):
    result = generate(FULL_PATH, str(tmp_path / 'boot_out.json'))
    assert 'boot_meta' in result
    assert result['boot_meta']['runtime_pair_hash'] == ''

# TC-2: runtime_pair_hash 전달 시 boot_meta에 정상 기록
def test_tc2_runtime_pair_hash_recorded(tmp_path):
    result = generate(FULL_PATH, str(tmp_path / 'boot_out.json'),
                      runtime_pair_hash=MOCK_HASH)
    assert result['boot_meta']['runtime_pair_hash'] == MOCK_HASH

# TC-3: runtime_pair_rule 존재 확인
def test_tc3_runtime_pair_rule_present(tmp_path):
    result = generate(FULL_PATH, str(tmp_path / 'boot_out.json'),
                      runtime_pair_hash=MOCK_HASH)
    rule = result['boot_meta'].get('runtime_pair_rule', '')
    assert 'BOOT_REFERENCES_RUNTIME_ONLY' in rule
    assert 'RUNTIME must not reference BOOT hash' not in rule

# TC-4: boot_is_ssot=False 불변 확인
def test_tc4_boot_is_ssot_false(tmp_path):
    result = generate(FULL_PATH, str(tmp_path / 'boot_out.json'),
                      runtime_pair_hash=MOCK_HASH)
    assert result['boot_meta']['boot_is_ssot'] is False

# TC-5: 출력 파일 정상 생성 확인
def test_tc5_output_file_written(tmp_path):
    out = tmp_path / 'boot_out.json'
    generate(FULL_PATH, str(out), runtime_pair_hash=MOCK_HASH)
    assert out.exists()
    with open(out) as f:
        data = json.load(f)
    assert data['boot_meta']['runtime_pair_hash'] == MOCK_HASH

# TC-6: runtime_pair_hash가 BOOT 본문(boot_meta 외부)에 노출되지 않음
def test_tc6_hash_not_in_root(tmp_path):
    result = generate(FULL_PATH, str(tmp_path / 'boot_out.json'),
                      runtime_pair_hash=MOCK_HASH)
    top_keys = set(result.keys()) - {'boot_meta'}
    assert 'runtime_pair_hash' not in top_keys
