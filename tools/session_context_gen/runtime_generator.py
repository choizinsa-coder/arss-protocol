"""
runtime_generator.py
PT-S81-ARCH-001 Phase 2
Role: SESSION_STATE_RUNTIME content_hash 산출 및 BOOT 주입용 메타데이터 반환
Rule: RUNTIME은 BOOT hash를 역참조하지 않는다 (단방향: RUNTIME → BOOT)
RUNTIME 실제 구조 기반 (S87 확인):
  - session_id 없음 → session_count 사용
  - schema_version 없음 → RUNTIME에 미포함, 체크 제외
  - chain_tip → chain.tip
  - _zone: SESSION_STATE_RUNTIME (zone 식별자)
"""
import json
import hashlib
from pathlib import Path

ARSS_ROOT = Path('/opt/arss/engine/arss-protocol')
RUNTIME_PATH = ARSS_ROOT / 'SESSION_STATE_RUNTIME.json'


def load_runtime(path: Path = RUNTIME_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f'RUNTIME not found: {path}')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def compute_content_hash(data: dict) -> str:
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def generate_runtime_meta(path: Path = RUNTIME_PATH) -> dict:
    """
    RUNTIME 로드 → content_hash 산출 → BOOT 주입용 메타데이터 반환
    반환값에 boot_hash 포함 금지 (단방향 규칙)
    """
    data = load_runtime(path)

    # 역참조 금지 검증
    forbidden_keys = {'boot_hash', 'boot_ref', 'boot_pair_hash'}
    found = forbidden_keys & set(data.keys())
    if found:
        raise ValueError(f'RUNTIME contains forbidden boot-reference keys: {found}')

    content_hash = compute_content_hash(data)

    chain_tip = data.get('chain', {}).get('tip', '')

    meta = {
        'runtime_content_hash': content_hash,
        'session_count': data.get('session_count', ''),
        'generated_at': data.get('generated_at', ''),
        'chain_tip': chain_tip,
        'zone': data.get('_zone', ''),
        'source_session': data.get('_source_session', ''),
    }
    return meta


def validate_runtime_integrity(path: Path = RUNTIME_PATH) -> dict:
    """RUNTIME 무결성 사전 검증 — BOOT 생성 전 호출"""
    result = {'status': 'UNKNOWN', 'checks': {}}
    try:
        data = load_runtime(path)
        result['checks']['file_exists'] = True
        result['checks']['json_valid'] = True

        # zone 식별자 확인
        zone = data.get('_zone', '')
        result['checks']['zone_correct'] = (zone == 'SESSION_STATE_RUNTIME')

        # 역참조 금지
        forbidden_keys = {'boot_hash', 'boot_ref', 'boot_pair_hash'}
        found = forbidden_keys & set(data.keys())
        result['checks']['no_boot_reference'] = len(found) == 0

        # 필수 필드
        result['checks']['session_count_present'] = bool(data.get('session_count') is not None)
        result['checks']['generated_at_present'] = bool(data.get('generated_at'))
        chain_tip = data.get('chain', {}).get('tip', '')
        result['checks']['chain_tip_present'] = bool(chain_tip)

        all_pass = all([
            result['checks']['zone_correct'],
            result['checks']['no_boot_reference'],
            result['checks']['session_count_present'],
            result['checks']['generated_at_present'],
            result['checks']['chain_tip_present'],
        ])
        result['status'] = 'PASS' if all_pass else 'FAIL'
    except FileNotFoundError:
        result['checks']['file_exists'] = False
        result['status'] = 'FAIL'
    except json.JSONDecodeError:
        result['checks']['json_valid'] = False
        result['status'] = 'FAIL'
    return result


if __name__ == '__main__':
    import sys
    print('=== runtime_generator.py ===')
    val = validate_runtime_integrity()
    print(f'Integrity: {val["status"]}')
    for k, v in val['checks'].items():
        print(f'  {k}: {v}')
    if val['status'] == 'PASS':
        meta = generate_runtime_meta()
        print(f'runtime_content_hash: {meta["runtime_content_hash"]}')
        print(f'session_count:        {meta["session_count"]}')
        print(f'chain_tip:            {meta["chain_tip"]}')
        print(f'zone:                 {meta["zone"]}')
        print(f'source_session:       {meta["source_session"]}')
    else:
        print('HARD STOP: RUNTIME integrity FAIL')
        sys.exit(1)
