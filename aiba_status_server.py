#!/usr/bin/env python3
ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
AIBA Status Server v0.9
Changes from v0.8:
- Added POST /rpu/issue endpoint (WF-05 v2 orchestration layer)
  - Step 0: Token auth (AIBA_TOKEN_CADDY)
  - Step 1: Input field validation
  - Step 2: event_type allowlist check (INTERPRETATION_RULE.json, LESSON-013)
  - Step 3: PEC capture
  - Step 4: rpu_atomic_issuer.py subprocess call
  - Step 5: vps_verifier_bridge.py post-validation
"""

import os
import glob
import json
import time
import hmac
import hashlib
import psutil
import subprocess
import datetime
from flask import Flask, request, jsonify
from functools import wraps

app = Flask(__name__)

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR             = '/opt/arss/engine/arss-protocol'
SESSION_CONTEXT_PATH = os.path.join(BASE_DIR, 'SESSION_CONTEXT.json')
SYNC_METADATA_PATH   = os.path.join(BASE_DIR, 'sync_metadata.json')
INTERPRETATION_RULE_PATH = os.path.join(BASE_DIR, 'INTERPRETATION_RULE.json')
ISSUER_PATH          = os.path.join(BASE_DIR, 'tools', 'rpu_atomic_issuer.py')
TOKEN_PATH           = os.path.join(BASE_DIR, ".approval_token")
VERIFIER_PATH        = os.path.join(BASE_DIR, 'scripts', 'workflow', 'vps_verifier_bridge.py')
EVIDENCE_DIR         = os.path.join(BASE_DIR, 'evidence')
SCORING_LEDGER_PATH  = os.path.join(EVIDENCE_DIR, 'scoring_ledger.json')
PEC_FAILURES_DIR     = os.path.join(BASE_DIR, 'logs', 'pec_failures')

# Bearer 토큰 (에이전트별)
TOKENS = {
    'caddy':  os.environ.get('AIBA_TOKEN_CADDY',  'caddy-token-placeholder'),
    'domi':   os.environ.get('AIBA_TOKEN_DOMI',   'domi-token-placeholder'),
    'jeni':   os.environ.get('AIBA_TOKEN_JENI',   'jeni-token-placeholder'),
    'system': os.environ.get('AIBA_TOKEN_SYSTEM', 'system-token-placeholder'),
}

# HMAC 시크릿
HMAC_SECRET = os.environ.get('HMAC_SECRET', 'hmac-secret-placeholder').encode()

# WRITE 권한 에이전트
WRITE_AGENTS = {'caddy', 'system'}

# ── 인증 헬퍼 ─────────────────────────────────────────────────────────────────
def verify_token(auth_header):
    """Bearer 토큰 검증 → 에이전트명 반환, 실패 시 None"""
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header[7:]
    for agent, t in TOKENS.items():
        if hmac.compare_digest(token, t):
            return agent
    return None


def verify_signature(agent, body_bytes):
    """X-AIBA-Signature HMAC 검증"""
    sig_header = request.headers.get('X-AIBA-Signature', '')
    expected = hmac.new(HMAC_SECRET, body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig_header, expected)


def require_auth(require_write=False):
    """인증 데코레이터"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            agent = verify_token(request.headers.get('Authorization', ''))
            if not agent:
                return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
            if require_write and agent not in WRITE_AGENTS:
                return jsonify({'status': 'error', 'message': 'Forbidden — WRITE권한 없음'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── 기존 엔드포인트 ───────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    """인증 없음 — 시스템 헬스 체크"""
    cpu    = psutil.cpu_percent(interval=0.5)
    mem    = psutil.virtual_memory()
    disk   = psutil.disk_usage('/')
    return jsonify({
        'status': 'ok',
        'server': 'aiba_status_server',
        'version': 'v0.9',
        'timestamp': int(time.time()),
        'cpu_percent': cpu,
        'memory': {
            'total_mb': round(mem.total / 1024**2, 1),
            'used_mb':  round(mem.used  / 1024**2, 1),
            'percent':  mem.percent,
        },
        'disk': {
            'total_gb': round(disk.total / 1024**3, 2),
            'used_gb':  round(disk.used  / 1024**3, 2),
            'percent':  disk.percent,
        },
    })





@app.route("/v1/system/time", methods=["GET"])
def get_system_time():
    """인증 없음 — KST 현재 시각 반환 (UTS v1.0-Rev.A)
    A안: 기존 필드 유지 + PT-S71-001 계약 필드 추가 (S95)
    계약 필드: ok / source / timestamp / epoch_ms
    레거시 필드: current_kst / current_utc / utc_offset / unix_timestamp (하위 호환 유지)
    """
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    now_kst = datetime.now(KST)
    now_utc = datetime.now(timezone.utc)
    ms = now_kst.strftime("%f")[:3]
    timestamp_iso = now_kst.strftime(f"%Y-%m-%dT%H:%M:%S.{ms}+09:00")
    return jsonify({
        "ok": True,
        "source": "AIBA_STATUS_SERVER_CLOCK",
        "timezone": "Asia/Seoul",
        "timestamp": timestamp_iso,
        "epoch_ms": int(now_utc.timestamp() * 1000),
        "current_kst": now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "current_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "utc_offset": "+09:00",
        "unix_timestamp": int(now_utc.timestamp()),
    })


@app.route('/approval-token', methods=['GET'])
def get_approval_token():
    auth = request.headers.get('Authorization', '')
    if auth != f"Bearer {TOKENS['caddy']}":
        return jsonify({'error': 'unauthorized'}), 401

    if not os.path.exists(TOKEN_PATH):
        return jsonify({'error': 'token not found'}), 404

    with open(TOKEN_PATH, 'r', encoding='utf-8') as f:
        token_data = json.load(f)

    from zoneinfo import ZoneInfo
    from datetime import datetime
    expires_str = token_data.get('expires_at_kst')
    if not expires_str:
        return jsonify({'error': 'token missing expiry'}), 422

    expires_dt = datetime.fromisoformat(expires_str)
    now_kst = datetime.now(ZoneInfo('Asia/Seoul'))
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=ZoneInfo('Asia/Seoul'))

    if now_kst > expires_dt:
        return jsonify({'error': 'token expired', 'expired_at': expires_str}), 410

    return jsonify(token_data), 200

@app.route('/session/current', methods=['GET'])
@require_auth()
def get_session_current():
    """session_count runtime 반환 — /status 대체 경량 엔드포인트 (Option A-2)"""
    try:
        with open(SESSION_CONTEXT_PATH, 'r', encoding='utf-8') as f:
            ctx = json.load(f)
        session_count = ctx.get('session_count', None)
        if session_count is None:
            return jsonify({'status': 'error', 'message': 'session_count not found'}), 500
        return jsonify({'status': 'ok', 'session_count': int(session_count)})
    except FileNotFoundError:
        return jsonify({'status': 'error', 'message': 'SESSION_CONTEXT.json not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/status', methods=['GET'])
@require_auth()
def get_status():
    """현재 상태 반환"""
    try:
        with open(SESSION_CONTEXT_PATH, 'r', encoding='utf-8') as f:
            ctx = json.load(f)
        return jsonify({'status': 'ok', 'data': ctx})
    except FileNotFoundError:
        return jsonify({'status': 'error', 'message': 'SESSION_CONTEXT.json not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/status/update', methods=['POST'])
@require_auth(require_write=True)
def update_status():
    """상태 업데이트 (WRITE권한 필요)"""
    body = request.get_data()
    if not verify_signature(None, body):
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403
    try:
        payload = json.loads(body)
        with open(SESSION_CONTEXT_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok', 'message': 'SESSION_CONTEXT updated'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/file-hash', methods=['GET'])
@require_auth()
def file_hash():
    """파일 SHA256 해시 조회"""
    file_path = request.args.get('path', SESSION_CONTEXT_PATH)
    include_content = request.args.get('content', 'false').lower() == 'true'
    if not os.path.abspath(file_path).startswith(BASE_DIR):
        return jsonify({'status': 'error', 'message': 'Forbidden path'}), 403
    try:
        with open(file_path, 'rb') as f:
            raw_bytes = f.read()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        result = {'status': 'ok', 'path': file_path, 'sha256': digest}
        if include_content:
            result['content'] = json.loads(raw_bytes.decode('utf-8'))
        return jsonify(result)
    except FileNotFoundError:
        return jsonify({'status': 'error', 'message': 'File not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── v0.8 신규 엔드포인트 ──────────────────────────────────────────────────────

@app.route('/session-context', methods=['GET'])
@require_auth()
def get_session_context():
    """SESSION_CONTEXT.json 전체 내용 반환 (n8n WF-04 Layer1 용)"""
    try:
        with open(SESSION_CONTEXT_PATH, 'r', encoding='utf-8') as f:
            raw  = f.read()
            data = json.loads(raw)
        sha256 = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        return jsonify({
            'status': 'ok',
            'data':   data,
            'sha256': sha256,
            'size':   len(raw),
        })
    except FileNotFoundError:
        return jsonify({'status': 'error', 'message': 'SESSION_CONTEXT.json not found'}), 404
    except json.JSONDecodeError as e:
        return jsonify({'status': 'error', 'message': 'JSON parse error: ' + str(e)}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/sync-metadata', methods=['GET'])
@require_auth()
def get_sync_metadata():
    """sync_metadata.json 읽기 (n8n WF-04 Layer2B 용)"""
    try:
        with open(SYNC_METADATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({'status': 'ok', 'data': data})
    except FileNotFoundError:
        return jsonify({'status': 'ok', 'data': {}})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/sync-metadata', methods=['POST'])
@require_auth(require_write=True)
def update_sync_metadata():
    """sync_metadata.json 갱신 (n8n WF-04 Layer5 용, WRITE권한 필요)"""
    try:
        payload = request.get_json(force=True)
        if payload is None:
            return jsonify({'status': 'error', 'message': 'No valid JSON payload'}), 400
        with open(SYNC_METADATA_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok', 'message': 'sync_metadata updated'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── v0.9 신규 엔드포인트 ──────────────────────────────────────────────────────

def _get_chain_tip():
    """evidence/scoring_ledger.json에서 현재 chain_tip 취득 (LESSON-011: 서버 자동 취득)"""
    with open(SCORING_LEDGER_PATH, 'r', encoding='utf-8') as f:
        ledger = json.load(f)
    tip = ledger.get('chain_tip') or ledger.get('chain', {}).get('tip')
    if not tip or len(tip) < 16:
        raise ValueError(f'chain_tip 취득 실패 또는 비정상값: {tip!r}')
    return tip


def _get_allowed_event_types():
    """INTERPRETATION_RULE.json에서 허용 event_type 목록 취득 (LESSON-013)"""
    with open(INTERPRETATION_RULE_PATH, 'r', encoding='utf-8') as f:
        rule = json.load(f)
    # score_rules_v2_1 우선, 없으면 score_rules_v1 fallback
    active_rules = rule.get('score_rules_v2_1') or rule.get('score_rules', {})
    event_types = active_rules.get('event_types', {})
    if not event_types:
        active_rules = rule.get('score_rules_v1', {})
        event_types = active_rules.get('event_types', {})
    if not event_types:
        raise ValueError('INTERPRETATION_RULE에서 허용 event_types 로딩 실패')
    return event_types


def _save_pec_failure(pec_data: dict):
    """PEC 실패 로그 저장 (Phase 3 로그 보강)"""
    os.makedirs(PEC_FAILURES_DIR, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')
    path = os.path.join(PEC_FAILURES_DIR, f'PEC_FAIL_{ts}.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(pec_data, f, ensure_ascii=False, indent=2)
    except Exception as _e:
        import logging; logging.warning("PEC log save failed: %s", _e)
    return path


class PecContext:
    """PEC 상태 변경 경계 캡슐화 — rpu_issue() 실행 주기 내부 전용 (RULE-7 해소)"""

    def __init__(self):
        self._log = {
            'endpoint': 'POST /rpu/issue',
            'requested_at': datetime.datetime.utcnow().isoformat() + 'Z',
            'failed_at_step': None,
            'reason': None,
        }

    def add_failure(self, step: str, reason: str):
        self._log['failed_at_step'] = step
        self._log['reason'] = reason

    def add_revalidation(self, result: str):
        self._log['revalidation'] = result

    def add_snapshot(self, pec: dict):
        self._log['pec'] = pec

    def add_input(self, input_info: dict):
        self._log['input'] = input_info

    def add_issuer_result(self, result: dict):
        self._log['issuer_result'] = result

    def add_verifier_result(self, result: dict):
        self._log['verifier_result'] = result

    def to_dict(self) -> dict:
        return dict(self._log)


def _revalidate_approval_contract(data: dict, context: PecContext):
    """R1~R4 approval_id 검증 — 보안 경계. 축약/생략 금지."""
    approval_id = data.get('approval_id')
    if not approval_id:
        return {'ok': True}

    import glob as _glob

    # R1: approval_id → eag_approvals/ 레코드 존재 확인
    approval_files = _glob.glob(
        os.path.join(BASE_DIR, 'evidence', 'eag_approvals', '*.json')
    )
    approval_record = None
    for af in approval_files:
        try:
            with open(af) as f:
                rec = json.load(f)
                if rec.get('approval_id') == approval_id:
                    approval_record = rec
                    break
        except Exception as _e:
            import logging; logging.warning("approval_record parse failed: %s", _e)

    if not approval_record:
        reason = f'approval_id {approval_id} not found in eag_approvals/'
        context.add_failure('R1_EXISTENCE', reason)
        return {'ok': False, 'step': 'R1_EXISTENCE', 'reason': reason,
                'http_status': 403,
                'response': {'status': 'FAILED_CLOSED', 'stage': 'R1_EXISTENCE', 'reason': reason}}

    # R2: approval record ↔ .approval_token hash binding
    token_data = None
    try:
        with open(TOKEN_PATH) as f:
            token_data = json.load(f)
        if token_data.get('approval_hash') != approval_record.get('approval_hash'):
            raise ValueError('approval_hash mismatch')
    except Exception as e:
        context.add_failure('R2_BINDING', str(e))
        return {'ok': False, 'step': 'R2_BINDING', 'reason': str(e),
                'http_status': 403,
                'response': {'status': 'FAILED_CLOSED', 'stage': 'R2_BINDING', 'reason': str(e)}}

    # R3: event_type → approval source_ref 범위 확인
    req_event_type    = approval_record.get('event_type', '')
    approved_source_ref = approval_record.get('source_ref', '')
    if approved_source_ref and req_event_type and req_event_type not in approved_source_ref:
        reason = f'event_type {req_event_type} out of approval scope {approved_source_ref}'
        context.add_failure('R3_SCOPE', reason)
        return {'ok': False, 'step': 'R3_SCOPE', 'reason': reason,
                'http_status': 403,
                'response': {'status': 'FAILED_CLOSED', 'stage': 'R3_SCOPE', 'reason': reason}}

    # R4: canonical payload hash 무결성 확인 (문자열 조립/정렬/인코딩 기준 불변)
    import hashlib as _hashlib
    payload_str  = json.dumps({
        'event_type': approval_record.get('event_type', ''),
        'content':    approval_record.get('content', ''),
        'actor_id':   approval_record.get('actor_id', ''),
    }, sort_keys=True, ensure_ascii=False)
    payload_hash = 'sha256:' + _hashlib.sha256(payload_str.encode()).hexdigest()
    if token_data.get('event_hash') and payload_hash != token_data.get('event_hash'):
        reason = f'payload hash {payload_hash} != token event_hash'
        context.add_failure('R4_INTEGRITY', reason)
        return {'ok': False, 'step': 'R4_INTEGRITY', 'reason': reason,
                'http_status': 403,
                'response': {'status': 'FAILED_CLOSED', 'stage': 'R4_INTEGRITY', 'reason': reason}}

    context.add_revalidation('R1~R4 ALL PASS')
    return {'ok': True, 'approval_record': approval_record}


def _validate_rpu_issue_input(data: dict, context: PecContext):
    """Step 1: 입력 필드 완결성 검사 + 필드 추출"""
    if data is None:
        context.add_failure('Step 1', 'JSON body 없음')
        return {'ok': False, 'step': 'Step 1', 'reason': 'JSON body 없음',
                'http_status': 400,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 1', 'reason': 'JSON body 없음'}}

    required_fields = ['content', 'event_type', 'session_id']
    missing = [fld for fld in required_fields if not data.get(fld)]
    if missing:
        reason = f'필수 필드 누락: {missing}'
        context.add_failure('Step 1', reason)
        return {'ok': False, 'step': 'Step 1', 'reason': reason,
                'http_status': 400,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 1',
                               'reason': reason, 'missing_fields': missing}}

    return {
        'ok':        True,
        'actor_id':  data.get('actor_id', ''),
        'content':   data['content'],
        'event_type': data['event_type'],
        'session_id': data['session_id'],
        'source_ref': data.get('source_ref', ''),
        'dry_run':   bool(data.get('dry_run', False)),
    }


def _check_rpu_event_type_allowlist(event_type: str, context: PecContext):
    """Step 2: event_type 허용 목록 확인 (LESSON-013)"""
    try:
        allowed = _get_allowed_event_types()
    except Exception as e:
        reason = f'허용 목록 로딩 실패: {e}'
        context.add_failure('Step 2', reason)
        return {'ok': False, 'step': 'Step 2', 'reason': reason,
                'http_status': 500,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 2', 'reason': reason}}

    if event_type not in allowed:
        reason = f'event_type "{event_type}" 허용 목록 미포함. 허용: {allowed}'
        context.add_failure('Step 2', reason)
        return {'ok': False, 'step': 'Step 2', 'reason': reason,
                'http_status': 422,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 2', 'reason': reason}}

    return {'ok': True}


def _capture_rpu_issue_pec_snapshot(context: PecContext):
    """Step 3: chain_tip + 파일 존재 확인"""
    try:
        chain_tip = _get_chain_tip()
        context.add_snapshot({
            'captured_at':      datetime.datetime.utcnow().isoformat() + 'Z',
            'chain_tip':        chain_tip,
            'chain_tip_length': len(chain_tip),
            'issuer_path':      ISSUER_PATH,
            'verifier_path':    VERIFIER_PATH,
            'evidence_dir':     EVIDENCE_DIR,
            'issuer_exists':    os.path.exists(ISSUER_PATH),
            'verifier_exists':  os.path.exists(VERIFIER_PATH),
            'ledger_exists':    os.path.exists(SCORING_LEDGER_PATH),
        })
    except Exception as e:
        reason = f'PEC 캡처 실패: {e}'
        context.add_failure('Step 3', reason)
        return {'ok': False, 'step': 'Step 3', 'reason': reason,
                'http_status': 500,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 3', 'reason': reason}}

    for label, path in [('issuer', ISSUER_PATH), ('verifier', VERIFIER_PATH)]:
        if not os.path.exists(path):
            reason = f'{label} 파일 없음: {path}'
            context.add_failure('Step 3', reason)
            return {'ok': False, 'step': 'Step 3', 'reason': reason,
                    'http_status': 500,
                    'response': {'status': 'FAIL', 'failed_at_step': 'Step 3', 'reason': reason}}

    return {'ok': True, 'chain_tip': chain_tip}


def _invoke_rpu_atomic_issuer(input_state: dict, context: PecContext):
    """Step 4: rpu_atomic_issuer.py subprocess 호출. tmp_event 생성/삭제 동일 함수 내 완결."""
    import tempfile, json as _json

    tmp_path = None
    try:
        event_payload = {
            'actor_id':   input_state['actor_id'],
            'content':    input_state['content'],
            'event_type': input_state['event_type'],
            'session_id': input_state['session_id'],
        }
        if input_state['source_ref']:
            event_payload['source_ref'] = input_state['source_ref']

        tmp_event = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False,
            dir='/tmp', encoding='utf-8'
        )
        _json.dump(event_payload, tmp_event, ensure_ascii=False)
        tmp_event.flush()
        tmp_event.close()
        tmp_path = tmp_event.name

        # session_count: approval_token session_id에서 파싱
        try:
            with open(TOKEN_PATH, 'r', encoding='utf-8') as _tk:
                _tk_data = json.load(_tk)
            _token_sid = _tk_data.get('session_id', '')
            import re as _re
            _m = _re.search(r'S(\d+)$', _token_sid)
            if not _m:
                raise ValueError(f'session_id 파싱 실패: {_token_sid}')
            _session_count = int(_m.group(1))
        except Exception as e:
            reason = f'SESSION_COUNT_LOAD_FAILED: {e}'
            context.add_failure('Step 4', reason)
            return {'ok': False, 'step': 'Step 4', 'reason': reason,
                    'http_status': 500,
                    'response': {'status': 'error', 'reason': reason}}

        cmd = ['python3', ISSUER_PATH,
               '--event-file',     tmp_path,
               '--approval-token', TOKEN_PATH,
               '--session-count',  str(_session_count),
               '--actor-id',       input_state['actor_id']]
        if input_state['dry_run']:
            cmd += ['--dry-run']

        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=60, cwd=BASE_DIR,
            env=os.environ.copy()
        )
        context.add_issuer_result({
            'returncode':   result.returncode,
            'stdout_tail':  result.stdout[-500:] if result.stdout else '',
            'stderr_tail':  result.stderr[-500:] if result.stderr else '',
        })

        if result.returncode != 0:
            reason = f'issuer 실패 (returncode={result.returncode})'
            context.add_failure('Step 4', reason)
            return {'ok': False, 'step': 'Step 4', 'reason': reason,
                    'http_status': 500,
                    'response': {'status': 'FAIL', 'failed_at_step': 'Step 4',
                                   'reason': reason,
                                   'issuer_stderr': result.stderr[-500:]}}

        # stdout에서 rpu_id, new_chain_tip 파싱 (LESSON-011: 64자 full hash)
        rpu_id = None
        new_chain_tip = None
        for line in result.stdout.splitlines():
            if 'rpu_id' in line.lower():
                try:
                    rpu_id = line.split(':', 1)[1].strip().strip('"').strip("'").strip(',')
                except Exception as _e:
                    import logging; logging.debug("rpu_id parse skip: %s", _e)
            if 'chain_tip' in line.lower() or 'chain_hash' in line.lower():
                try:
                    candidate = line.split(':', 1)[1].strip().strip('"').strip("'").strip(',')
                    if len(candidate) == 64:
                        new_chain_tip = candidate
                except Exception as _e:
                    import logging; logging.debug("chain_tip parse skip: %s", _e)

        return {'ok': True, 'rpu_id': rpu_id, 'new_chain_tip': new_chain_tip}

    except subprocess.TimeoutExpired:
        reason = 'issuer subprocess timeout (60s)'
        context.add_failure('Step 4', reason)
        return {'ok': False, 'step': 'Step 4', 'reason': reason,
                'http_status': 500,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 4', 'reason': reason}}
    except Exception as e:
        reason = f'issuer 호출 예외: {e}'
        context.add_failure('Step 4', reason)
        return {'ok': False, 'step': 'Step 4', 'reason': reason,
                'http_status': 500,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 4', 'reason': reason}}
    finally:
        # tmp_event cleanup — 성공/실패 무관 항상 수행. cleanup 실패가 issuer 결과 덮어쓰기 금지.
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception as _ce:
                import logging; logging.warning("tmp_event cleanup failed: %s", _ce)


def _verify_rpu_post_issuance(dry_run: bool, context: PecContext):
    """Step 5: vps_verifier_bridge.py 후검증. dry_run=False 시 우회 경로 없음."""
    if dry_run:
        return {'ok': True, 'verifier_result': 'SKIPPED_DRY_RUN'}

    try:
        v_result = subprocess.run(
            ['python3', VERIFIER_PATH, '--chain-dir', EVIDENCE_DIR],
            capture_output=True, text=True,
            timeout=30, cwd=BASE_DIR,
            env=os.environ.copy()
        )
        context.add_verifier_result({
            'returncode':  v_result.returncode,
            'stdout_tail': v_result.stdout[-300:] if v_result.stdout else '',
        })

        if v_result.returncode != 0:
            reason = f'verifier FAIL (returncode={v_result.returncode})'
            context.add_failure('Step 5', reason)
            return {'ok': False, 'step': 'Step 5', 'reason': reason,
                    'http_status': 500,
                    'response': {'status': 'FAIL', 'failed_at_step': 'Step 5',
                                   'reason': reason,
                                   'verifier_stdout': v_result.stdout[-300:]}}

        return {'ok': True, 'verifier_result': 'PASS'}

    except subprocess.TimeoutExpired:
        reason = 'verifier subprocess timeout (30s)'
        context.add_failure('Step 5', reason)
        return {'ok': False, 'step': 'Step 5', 'reason': reason,
                'http_status': 500,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 5', 'reason': reason}}
    except Exception as e:
        reason = f'verifier 호출 예외: {e}'
        context.add_failure('Step 5', reason)
        return {'ok': False, 'step': 'Step 5', 'reason': reason,
                'http_status': 500,
                'response': {'status': 'FAIL', 'failed_at_step': 'Step 5', 'reason': reason}}


@app.route('/rpu/issue', methods=['POST'])
@require_auth(require_write=True)
def rpu_issue():
    """
    WF-05 v2 오케스트레이션 엔드포인트 (Orchestrator — RULE-5 분해 S161)
    Step 0: 인증 (require_auth 데코레이터가 처리)
    Step 1: 입력 필드 완결성 검사
    Step 2: event_type 허용 목록 확인 (LESSON-013)
    Step 3: PEC 캡처
    Step 4: rpu_atomic_issuer.py subprocess 호출
    Step 5: vps_verifier_bridge.py 후검증
    """
    context = PecContext()
    data    = request.get_json(force=True, silent=True) or {}

    # R1~R4 Revalidation Contract
    rv = _revalidate_approval_contract(data, context)
    if not rv['ok']:
        _save_pec_failure(context.to_dict())
        return jsonify(rv['response']), rv['http_status']

    # Step 1: 입력 검증
    input_state = _validate_rpu_issue_input(data, context)
    if not input_state['ok']:
        _save_pec_failure(context.to_dict())
        return jsonify(input_state['response']), input_state['http_status']

    context.add_input({
        'actor_id':       input_state['actor_id'],
        'event_type':     input_state['event_type'],
        'session_id':     input_state['session_id'],
        'source_ref':     input_state['source_ref'],
        'dry_run':        input_state['dry_run'],
        'content_length': len(input_state['content']),
    })

    # Step 2: event_type 허용 목록
    allow_state = _check_rpu_event_type_allowlist(input_state['event_type'], context)
    if not allow_state['ok']:
        _save_pec_failure(context.to_dict())
        return jsonify(allow_state['response']), allow_state['http_status']

    # Step 3: PEC 캡처
    pec_state = _capture_rpu_issue_pec_snapshot(context)
    if not pec_state['ok']:
        _save_pec_failure(context.to_dict())
        return jsonify(pec_state['response']), pec_state['http_status']

    # Step 4: issuer subprocess
    issuer_state = _invoke_rpu_atomic_issuer(input_state, context)
    if not issuer_state['ok']:
        _save_pec_failure(context.to_dict())
        return jsonify(issuer_state['response']), issuer_state['http_status']

    # Step 5: 후검증 (dry_run=False 시 우회 불가)
    verify_state = _verify_rpu_post_issuance(input_state['dry_run'], context)
    if not verify_state['ok']:
        _save_pec_failure(context.to_dict())
        return jsonify(verify_state['response']), verify_state['http_status']

    return jsonify({
        'status':            'SUCCESS',
        'rpu_id':            issuer_state.get('rpu_id'),
        'chain_tip':         issuer_state.get('new_chain_tip') or pec_state['chain_tip'],
        'publication_state': 'DRY_RUN' if input_state['dry_run'] else 'PUSHED',
        'verifier_result':   verify_state['verifier_result'],
        'pec_captured_at':   context.to_dict()['pec']['captured_at'],
        'dry_run':           input_state['dry_run'],
    }), 200


# === APPROVAL POOL ENDPOINTS ===

@app.route('/approval-pool/ready', methods=['GET'])
def approval_pool_ready():
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {TOKENS["caddy"]}':
        return jsonify({"error": "unauthorized"}), 403

    pool_dir = os.path.join(BASE_DIR, 'evidence', 'eag_approvals')
    files = sorted(glob.glob(os.path.join(pool_dir, '*.json')))

    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                d = json.load(fp)
            if d.get('status') == 'READY':
                return jsonify({
                    "status": "READY",
                    "approval_id": d.get('approval_id'),
                    "event_hash": d.get('event_hash'),
                    "payload": {
                        "actor_id": d.get('actor_id'),
                        "content": d.get('content'),
                        "event_type": d.get('event_type'),
                        "session_id": d.get('session_id')
                    }
                }), 200
        except Exception as _e:
            import logging; logging.warning("pool entry skip: %s", _e)

    return jsonify({"status": "POOL_EMPTY"}), 200



@app.route('/approval-pool/add', methods=['POST'])
def approval_pool_add():
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {TOKENS["caddy"]}':
        return jsonify({"error": "unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    pool_dir = os.path.join(BASE_DIR, 'evidence', 'eag_approvals')
    files = sorted(glob.glob(os.path.join(pool_dir, '*.json')))

    target = None
    for f in files:
        if session_id in f:
            target = f
            break

    if not target:
        return jsonify({"error": "approval not found", "session_id": session_id}), 404

    with open(target, 'r') as f:
        approval_data = json.load(f)

    if approval_data.get('status') == 'READY':
        return jsonify({"error": "already READY", "file": os.path.basename(target)}), 409

    if approval_data.get('status') == 'CONSUMED':
        return jsonify({"error": "already CONSUMED", "file": os.path.basename(target)}), 409

    approval_data['status'] = 'READY'
    with open(target, 'w') as f:
        json.dump(approval_data, f, ensure_ascii=False, indent=2)

    return jsonify({
        "status": "registered",
        "session_id": session_id,
        "file": os.path.basename(target)
    }), 200

@app.route('/approval-pool/consume', methods=['POST'])
def approval_pool_consume():
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {TOKENS["caddy"]}':
        return jsonify({"error": "unauthorized"}), 403

    data = request.get_json(force=True)
    approval_id = data.get('approval_id')
    if not approval_id:
        return jsonify({"error": "approval_id required"}), 400

    pool_dir = os.path.join(BASE_DIR, 'evidence', 'eag_approvals')
    files = glob.glob(os.path.join(pool_dir, '*.json'))

    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                d = json.load(fp)
            if d.get('approval_id') != approval_id:
                continue
            if d.get('status') != 'READY':
                return jsonify({
                    "error": "not consumable",
                    "current_status": d.get('status')
                }), 409
            from datetime import datetime
            import pytz
            kst = pytz.timezone('Asia/Seoul')
            d['status'] = 'CONSUMED'
            d['consumed_at_kst'] = datetime.now(kst).isoformat()
            with open(f, 'w', encoding='utf-8') as fp:
                json.dump(d, fp, indent=2, ensure_ascii=False)
            return jsonify({
                "status": "CONSUMED",
                "approval_id": approval_id,
                "consumed_at_kst": d['consumed_at_kst']
            }), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "approval_id not found"}), 404


# ── 실행 ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
