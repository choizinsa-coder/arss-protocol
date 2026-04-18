#!/usr/bin/env python3
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
VERIFIER_PATH        = os.path.join(BASE_DIR, 'vps_verifier_bridge.py')
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
    """인증 없음 — KST 현재 시각 반환 (UTS v1.0-Rev.A)"""
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    now_kst = datetime.now(KST)
    now_utc = datetime.now(timezone.utc)
    return jsonify({
        "current_kst": now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "current_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "Asia/Seoul",
        "utc_offset": "+09:00",
        "unix_timestamp": int(now_utc.timestamp()),
        "source": "server_clock"
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
    if not os.path.abspath(file_path).startswith(BASE_DIR):
        return jsonify({'status': 'error', 'message': 'Forbidden path'}), 403
    try:
        with open(file_path, 'rb') as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        return jsonify({'status': 'ok', 'path': file_path, 'sha256': digest})
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
    except Exception:
        pass  # 로그 저장 실패는 주 흐름에 영향 없음
    return path


@app.route('/rpu/issue', methods=['POST'])
@require_auth(require_write=True)
def rpu_issue():
    """
    WF-05 v2 오케스트레이션 엔드포인트
    Step 0: 인증 (require_auth 데코레이터가 처리)
    Step 1: 입력 필드 완결성 검사
    Step 2: event_type 허용 목록 확인 (LESSON-013)
    Step 3: PEC 캡처
    Step 4: rpu_atomic_issuer.py subprocess 호출
    Step 5: vps_verifier_bridge.py 후검증
    """
    pec_log = {
        'endpoint': 'POST /rpu/issue',
        'requested_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'failed_at_step': None,
        'reason': None,
    }

    # ── Revalidation Contract R1~R4 ──────────────────────────────────
    approval_id = data.get('approval_id') if 'data' in dir() else None
    _data = request.get_json(force=True, silent=True) or {}
    approval_id = _data.get('approval_id')

    if approval_id:
        import glob as _glob

        # R1: 존재 증명 — approval_id → eag_approvals/ record 존재 확인
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
            except Exception:
                pass

        if not approval_record:
            pec_log['failed_at_step'] = 'R1_EXISTENCE'
            pec_log['reason'] = f'approval_id {approval_id} not found in eag_approvals/'
            _save_pec_failure(pec_log)
            return jsonify({'status': 'FAILED_CLOSED', 'stage': 'R1_EXISTENCE',
                            'reason': pec_log['reason']}), 403

        # R2: 결속 증명 — approval record ↔ .approval_token hash binding
        token_path = TOKEN_PATH
        try:
            with open(token_path) as f:
                token_data = json.load(f)
            if token_data.get('approval_hash') != approval_record.get('approval_hash'):
                raise ValueError('approval_hash mismatch')
        except Exception as e:
            pec_log['failed_at_step'] = 'R2_BINDING'
            pec_log['reason'] = str(e)
            _save_pec_failure(pec_log)
            return jsonify({'status': 'FAILED_CLOSED', 'stage': 'R2_BINDING',
                            'reason': pec_log['reason']}), 403

        # R3: 범위 증명 — approval record 기준 event_type → approval source_ref 범위 확인
        req_event_type = approval_record.get('event_type', '')
        approved_source_ref = approval_record.get('source_ref', '')
        # source_ref 미존재 시 패스 (하위 호환)
        if approved_source_ref and req_event_type and req_event_type not in approved_source_ref:
            pec_log['failed_at_step'] = 'R3_SCOPE'
            pec_log['reason'] = f'event_type {req_event_type} out of approval scope {approved_source_ref}'
            _save_pec_failure(pec_log)
            return jsonify({'status': 'FAILED_CLOSED', 'stage': 'R3_SCOPE',
                            'reason': pec_log['reason']}), 403

        # R4: 무결성 증명 — approval record 기준 canonical payload hash 확인
        import hashlib as _hashlib
        payload_str = json.dumps({
            'event_type': approval_record.get('event_type', ''),
            'content': approval_record.get('content', ''),
            'actor_id': approval_record.get('actor_id', ''),
        }, sort_keys=True, ensure_ascii=False)
        payload_hash = 'sha256:' + _hashlib.sha256(payload_str.encode()).hexdigest()
        if token_data.get('event_hash') and payload_hash != token_data.get('event_hash'):
            pec_log['failed_at_step'] = 'R4_INTEGRITY'
            pec_log['reason'] = f'payload hash {payload_hash} != token event_hash'
            _save_pec_failure(pec_log)
            return jsonify({'status': 'FAILED_CLOSED', 'stage': 'R4_INTEGRITY',
                            'reason': pec_log['reason']}), 403

        pec_log['revalidation'] = 'R1~R4 ALL PASS'

    # ── Step 1: 입력 필드 완결성 검사 ────────────────────────────────────────
    try:
        body = _data
        if body is None:
            raise ValueError('JSON body 없음')
        if body is None:
            raise ValueError('JSON body 없음')
    except Exception as e:
        pec_log.update({'failed_at_step': 'Step 1', 'reason': f'JSON 파싱 실패: {e}'})
        _save_pec_failure(pec_log)
        return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 1',
                        'reason': pec_log['reason']}), 400

    required_fields = ['content', 'event_type', 'session_id']
    missing = [f for f in required_fields if not body.get(f)]
    if missing:
        pec_log.update({'failed_at_step': 'Step 1', 'reason': f'필수 필드 누락: {missing}'})
        _save_pec_failure(pec_log)
        return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 1',
                        'reason': pec_log['reason'], 'missing_fields': missing}), 400

    actor_id   = body['actor_id']
    content    = body['content']
    event_type = body['event_type']
    session_id = body['session_id']
    source_ref = body.get('source_ref', '')
    dry_run    = bool(body.get('dry_run', False))

    pec_log['input'] = {
        'actor_id': actor_id,
        'event_type': event_type,
        'session_id': session_id,
        'source_ref': source_ref,
        'dry_run': dry_run,
        'content_length': len(content),
    }

    # ── Step 2: event_type 허용 목록 확인 (LESSON-013) ───────────────────────
    try:
        allowed = _get_allowed_event_types()
    except Exception as e:
        pec_log.update({'failed_at_step': 'Step 2', 'reason': f'허용 목록 로딩 실패: {e}'})
        _save_pec_failure(pec_log)
        return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 2',
                        'reason': pec_log['reason']}), 500

    if event_type not in allowed:
        pec_log.update({'failed_at_step': 'Step 2',
                        'reason': f'event_type "{event_type}" 허용 목록 미포함. 허용: {allowed}'})
        _save_pec_failure(pec_log)
        return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 2',
                        'reason': pec_log['reason']}), 422

    # ── Step 3: PEC 캡처 ──────────────────────────────────────────────────────
    try:
        chain_tip = _get_chain_tip()
        pec_log['pec'] = {
            'captured_at': datetime.datetime.utcnow().isoformat() + 'Z',
            'chain_tip': chain_tip,
            'chain_tip_length': len(chain_tip),
            'issuer_path': ISSUER_PATH,
            'verifier_path': VERIFIER_PATH,
            'evidence_dir': EVIDENCE_DIR,
            'issuer_exists': os.path.exists(ISSUER_PATH),
            'verifier_exists': os.path.exists(VERIFIER_PATH),
            'ledger_exists': os.path.exists(SCORING_LEDGER_PATH),
        }
    except Exception as e:
        pec_log.update({'failed_at_step': 'Step 3', 'reason': f'PEC 캡처 실패: {e}'})
        _save_pec_failure(pec_log)
        return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 3',
                        'reason': pec_log['reason']}), 500

    # issuer / verifier 파일 존재 확인
    for label, path in [('issuer', ISSUER_PATH), ('verifier', VERIFIER_PATH)]:
        if not os.path.exists(path):
            pec_log.update({'failed_at_step': 'Step 3',
                            'reason': f'{label} 파일 없음: {path}'})
            _save_pec_failure(pec_log)
            return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 3',
                            'reason': pec_log['reason']}), 500

    # ── Step 4: rpu_atomic_issuer.py subprocess 호출 ─────────────────────────
    import tempfile, json as _json
    try:
        issuer_env = os.environ.copy()
        event_payload = {
            'actor_id':   actor_id,
            'content':    content,
            'event_type': event_type,
            'session_id': session_id,
        }
        if source_ref:
            event_payload['source_ref'] = source_ref
        tmp_event = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False,
            dir='/tmp', encoding='utf-8'
        )
        _json.dump(event_payload, tmp_event, ensure_ascii=False)
        tmp_event.flush()
        tmp_event.close()
        # session_count: SESSION_CONTEXT.json에서 로드
        try:
            with open(SESSION_CONTEXT_PATH, 'r', encoding='utf-8') as _sc:
                _sc_data = json.load(_sc)
            _session_count = int(_sc_data.get('session_count', 0))
        except Exception as e:
            return jsonify({"status": "error", "reason": f"SESSION_COUNT_LOAD_FAILED: {e}"}), 500
        cmd = ['python3', ISSUER_PATH,
               '--event-file',     tmp_event.name,
               '--approval-token', TOKEN_PATH,
               '--session-count',  str(_session_count),
               '--actor-id',       actor_id]
        if dry_run:
            cmd += ['--dry-run']

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=BASE_DIR,
            env=issuer_env
        )
        pec_log['issuer_result'] = {
            'returncode': result.returncode,
            'stdout_tail': result.stdout[-500:] if result.stdout else '',
            'stderr_tail': result.stderr[-500:] if result.stderr else '',
        }

        if result.returncode != 0:
            pec_log.update({'failed_at_step': 'Step 4',
                            'reason': f'issuer 실패 (returncode={result.returncode})'})
            _save_pec_failure(pec_log)
            return jsonify({
                'status': 'FAIL',
                'failed_at_step': 'Step 4',
                'reason': pec_log['reason'],
                'issuer_stderr': result.stderr[-500:],
            }), 500

        # issuer stdout에서 rpu_id, new_chain_tip 파싱 시도
        rpu_id = None
        new_chain_tip = None
        for line in result.stdout.splitlines():
            if 'rpu_id' in line.lower():
                try:
                    rpu_id = line.split(':', 1)[1].strip().strip('"').strip("'").strip(',')
                except Exception:
                    pass
            if 'chain_tip' in line.lower() or 'chain_hash' in line.lower():
                try:
                    candidate = line.split(':', 1)[1].strip().strip('"').strip("'").strip(',')
                    if len(candidate) == 64:  # LESSON-011: 64자 full hash 확인
                        new_chain_tip = candidate
                except Exception:
                    pass

    except subprocess.TimeoutExpired:
        pec_log.update({'failed_at_step': 'Step 4', 'reason': 'issuer subprocess timeout (60s)'})
        _save_pec_failure(pec_log)
        return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 4',
                        'reason': pec_log['reason']}), 500
    except Exception as e:
        pec_log.update({'failed_at_step': 'Step 4', 'reason': f'issuer 호출 예외: {e}'})
        _save_pec_failure(pec_log)
        return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 4',
                        'reason': pec_log['reason']}), 500

    # ── Step 5: vps_verifier_bridge.py 후검증 ────────────────────────────────
    # dry_run이면 체인 변경 없으므로 verifier 후검증 skip (성공으로 처리)
    verifier_result = 'SKIPPED_DRY_RUN'
    if not dry_run:
        try:
            v_result = subprocess.run(
                ['python3', VERIFIER_PATH,
                 '--chain-dir', EVIDENCE_DIR],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=BASE_DIR,
                env=os.environ.copy()
            )
            pec_log['verifier_result'] = {
                'returncode': v_result.returncode,
                'stdout_tail': v_result.stdout[-300:] if v_result.stdout else '',
            }

            if v_result.returncode != 0:
                pec_log.update({'failed_at_step': 'Step 5',
                                'reason': f'verifier FAIL (returncode={v_result.returncode})'})
                _save_pec_failure(pec_log)
                return jsonify({
                    'status': 'FAIL',
                    'failed_at_step': 'Step 5',
                    'reason': pec_log['reason'],
                    'verifier_stdout': v_result.stdout[-300:],
                }), 500

            verifier_result = 'PASS'

        except subprocess.TimeoutExpired:
            pec_log.update({'failed_at_step': 'Step 5',
                            'reason': 'verifier subprocess timeout (30s)'})
            _save_pec_failure(pec_log)
            return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 5',
                            'reason': pec_log['reason']}), 500
        except Exception as e:
            pec_log.update({'failed_at_step': 'Step 5',
                            'reason': f'verifier 호출 예외: {e}'})
            _save_pec_failure(pec_log)
            return jsonify({'status': 'FAIL', 'failed_at_step': 'Step 5',
                            'reason': pec_log['reason']}), 500

    # ── 성공 반환 ─────────────────────────────────────────────────────────────
    return jsonify({
        'status':            'SUCCESS',
        'rpu_id':            rpu_id,
        'chain_tip':         new_chain_tip or chain_tip,
        'publication_state': 'DRY_RUN' if dry_run else 'PUSHED',
        'verifier_result':   verifier_result,
        'pec_captured_at':   pec_log['pec']['captured_at'],
        'dry_run':           dry_run,
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
        except Exception:
            continue

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
