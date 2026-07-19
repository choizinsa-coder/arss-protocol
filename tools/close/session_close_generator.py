"""
session_close_generator.py
SESSION CLOSE 5-file 번들 생성 정식 도구

EAG: EAG-S231-CLOSE-GENERATOR-001
위치: tools/close/session_close_generator.py
설계 근거: PT-S231-SESSION-CLOSE-GENERATOR (도미 설계 + Beo 보완 + 제니 TRUST_READY)
S273 개정: EAG-S273-BOOTCLOSE-REDESIGN-001
  - Step 5.5 Freeze Sync: journal last_entry_hash 자동 갱신
  - Step 5.6 Freeze Verification: govdoc_freeze_gate.py 즉시 검증
  - close_manifest.json 생성 (run_script 의존 제거)
  - CLOSE SUCCESS 조건: Freeze Verification PASS
S276 개정: EAG-S276-JENI-CTX-CLOSE-001
  - Step 5.7 Jeni Session Context 생성: 외부 제니 부팅용 세션 컨텍스트 자동 생성
  - 저장 경로: tools/design/JENI_SESSION_CONTEXT_S{n+1}.md
S357 개정: EAG-S357-IAPG-PHASE2-CONTRACT7-IMPL-001
  - IAPG-III 계약7 Write-Pointer-Last 원자발행
  - POINTER를 모든 번들 파일 완결·검증 이후 최후에 원자적으로 발행
  - _atomic_write_pointer(): tempfile+fsync+os.rename 원자 쓰기
  - _rollback_all(): 단계별 롤백 확장 (C7-4)
  - 발행 순서: 단계I(번들파일) -> 단계II(검증게이트) -> 단계III(POINTER 원자발행+사후작업)

사용법:
  # dry-run (파일 write 없음 — 산출 예정 경로·payload 출력만)
  python3 session_close_generator.py \\
      --session 231 --chain-tip abc1234 --prev-tip 0e4383e \\
      --delta-json /path/to/delta.json --dry-run

  # 실제 실행 (EAG approval-id 필수)
  python3 session_close_generator.py \\
      --session 231 --chain-tip abc1234 --prev-tip 0e4383e \\
      --delta-json /path/to/delta.json \\
      --approval-id EAG-S231-CLOSE-GENERATOR-001
"""
import argparse
import hashlib
import json
import os
import re
import tempfile
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path('/opt/arss/engine/arss-protocol')
KST = timezone(timedelta(hours=9))

APPROVAL_ID_PATTERN = re.compile(r'^EAG-S\d+-[A-Z0-9][A-Z0-9-]*[A-Z0-9]?$')

# ── DEP-S249-TIERD-MIGRATE-001 (목표 ③) ──────────────────────────
N_RETENTION = 3  # EAG-S405-BOOT-DIET-ARCHIVE-001
_RECORD_KEY_RE = re.compile(r'^(caddy_governance_record_s|visibility_metrics_s|system_changes_s)(\d+)$')  # EAG-S405-BOOT-DIET-ARCHIVE-001

GROUP_D_MIGRATE_WHITELIST = frozenset({
    'goal2_declaration', 'goal2_governance_rule',
    'visibility_metrics_current', 'on_the_horizon',
})

CANONICAL_EXCLUDE_KEYS = frozenset({
    'session_count', 'chain', 'session_delta', 'updated_at', 'generated_at',
    'context_hash', 'schema_version', 'sync_meta', 'pytest_status',
})
CEILING_LIMIT = 42

DELTA_REQUIRED_KEYS = {
    'session_reentry':         dict,
    'next_steps':              list,
    'agent_focus':             dict,
    'pytest_status':           dict,
    'system_changes':          dict,
    'caddy_governance_record': dict,
    'visibility_metrics':      dict,
    'session_delta':           dict,
    'sync_meta':               dict,
}

# ── S273: Freeze Sync 대상 경로 ───────────────────────────────────
FREEZE_TEST_PATH = ROOT / 'tests/test_goal1_freeze.py'
JOURNAL_PATH = ROOT / 'session_journal/session_journal.jsonl'
FREEZE_GATE_SCRIPT = ROOT / 'tools/guard/govdoc_freeze_gate.py'
FREEZE_SYNC_REPORT_PATH = ROOT / 'tools/close/freeze_sync_report.json'
CLOSE_MANIFEST_PATH = ROOT / 'tools/close/close_manifest.json'

# ── S276: Jeni Session Context 저장 경로 ──────────────────────────
JENI_SESSION_CONTEXT_SUBDIR = "tools/design"


# ── 유틸 ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(KST).isoformat()


def _today() -> str:
    return datetime.now(KST).strftime('%Y-%m-%d')


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _context_hash(sc: dict) -> str:
    sc_copy = {k: v for k, v in sc.items() if k != 'context_hash'}
    return hashlib.sha256(
        json.dumps(sc_copy, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()


def _validate_approval_id(approval_id: str) -> bool:
    return bool(APPROVAL_ID_PATTERN.match(approval_id))


def _rollback(generated_files: list) -> None:
    for fp in generated_files:
        try:
            Path(fp).unlink(missing_ok=True)
            print(f'[ROLLBACK] 삭제: {Path(fp).name}')
        except Exception as e:
            print(f'[ROLLBACK-WARN] 삭제 실패: {Path(fp).name} — {e}')

def _atomic_write_pointer(pointer: dict, target_path: Path) -> None:
    """
    IAPG-III 계약7 (C7-3): POINTER 원자 발행.
    tempfile(동일 디렉토리) -> json dump -> fsync -> os.rename (POSIX 원자 교체).
    실패 시 임시파일 정리 후 예외 재발생 — POINTER 미발행 상태 유지.
    EAG: EAG-S357-IAPG-PHASE2-CONTRACT7-IMPL-001
    """
    fd, tmp_path = tempfile.mkstemp(
        prefix='.pointer_tmp_',
        dir=str(target_path.parent),  # 동일 디렉토리 강제 (POSIX rename 원자성 보장)
        suffix='.tmp'
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(pointer, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno() if hasattr(f, 'fileno') else fd)
        os.rename(tmp_path, str(target_path))
        print(f'[OK] SESSION_CONTEXT_POINTER.json (atomic rename)')
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _rollback_all(stage: int, paths: dict) -> None:
    """
    IAPG-III 계약7 (C7-4): 단계별 롤백.
    stage에 따라 삭제 대상 파일 범위가 확장된다.
    paths 키: 'archive', 'sc_final', 'canonical', 'manifest', 'pointer'
    stage 1: archive
    stage 2: sc_final
    stage 3: sc_final, canonical
    stage 4: sc_final, canonical, manifest
    stage 5 (POINTER 발행 후 실패): sc_final, canonical, manifest, pointer
    C7-4: os.path.exists() 조건부 확인 후 삭제 (SC-5 반영)
    EAG: EAG-S357-IAPG-PHASE2-CONTRACT7-IMPL-001
    """
    STAGE_TARGETS = {
        1: ['archive'],
        2: ['sc_final'],
        3: ['sc_final', 'canonical'],
        4: ['sc_final', 'canonical', 'manifest'],
        5: ['sc_final', 'canonical', 'manifest', 'pointer'],
    }
    targets = STAGE_TARGETS.get(stage, [])
    for key in targets:
        fp = paths.get(key)
        if fp is None:
            continue
        p = Path(fp)
        if p.exists():
            try:
                p.unlink()
                print(f'[ROLLBACK] 삭제: {p.name} (stage={stage})')
            except Exception as e:
                print(f'[ROLLBACK-WARN] 삭제 실패: {p.name} — {e}')
        else:
            print(f'[ROLLBACK-SKIP] 미존재 (stage={stage}): {p.name}')




# ── S291 신규: Step 5 Session Report 자동 생성 ───────────────────

REPORTS_DIR = ROOT / 'SESSION_REPORTS'


def step_5_session_report(sc: dict, n: int) -> None:
    """
    SESSION_CONTEXT_S{n}_FINAL.json 기반으로
    AIBA_Daily_Session_Report_S{n}.md 를 SESSION_REPORTS/ 에 자동 생성.
    EAG: EAG-S291-SESSION-REPORT-AUTO-001
    - 파일 이미 존재 시 SKIP (덮어쓰기 금지)
    - 생성 실패 시 경고 후 SESSION CLOSE 계속 진행
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f'AIBA_Daily_Session_Report_S{n}.md'

    if out_path.exists():
        print(f'[SKIP] step_5_session_report: {out_path.name} 이미 존재')
        return

    try:
        chain     = sc.get('chain', {})
        chain_tip = chain.get('tip', 'unknown')

        pytest_st = sc.get('pytest_status', {})
        p_passed  = pytest_st.get('total_passed', '?')
        p_failed  = pytest_st.get('total_failed', '?')
        p_skipped = pytest_st.get('total_skipped', '?')
        p_note    = pytest_st.get('note', '')

        gov_key   = f'caddy_governance_record_s{n}'
        gov_rec   = sc.get(gov_key, {})
        eag_gates = gov_rec.get('eag_gates_this_session', [])
        incidents = gov_rec.get('incidents', [])
        oi_obs    = gov_rec.get('oi_observations', [])
        self_rep  = gov_rec.get('caddy_self_report', [])
        notable   = gov_rec.get('notable', '')
        stab      = gov_rec.get('stabilization_metrics', {})
        session_date = gov_rec.get('date', _today())

        sys_key  = f'system_changes_s{n}'
        sys_ch   = sc.get(sys_key, {})
        commits  = sys_ch.get('commits', [])
        changes  = sys_ch.get('changes', [])

        agent_focus = sc.get('agent_focus', {})
        next_steps  = sc.get('next_steps', [])

        vis_key   = f'visibility_metrics_s{n}'
        vis       = sc.get(vis_key, {})
        key_count = vis.get('M-01_active_canonical_key_count', '?')

        lines = []
        lines.append(f'# AIBA Daily Session Report — S{n}')
        lines.append('')
        lines.append(f'**날짜:** {session_date}')
        lines.append(f'**chain.tip:** `{chain_tip}`')
        lines.append(f'**pytest:** {p_failed} failed / {p_passed} passed / {p_skipped} skipped')
        lines.append(f'**생성:** session_close_generator.py 자동 생성 (EAG-S291-SESSION-REPORT-AUTO-001)')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 1. 세션 개요')
        lines.append('')
        lines.append('| 항목 | 값 |')
        lines.append('|------|---|')
        lines.append(f'| 세션 | S{n} |')
        lines.append(f'| chain.tip | `{chain_tip}` |')
        lines.append(f'| pytest | {p_failed} failed / {p_passed} passed / {p_skipped} skipped |')
        if p_note:
            lines.append(f'| pytest 비고 | {p_note} |')
        lines.append(f'| active canonical keys | {key_count} |')
        if commits:
            lines.append(f'| commits | {", ".join(f"`{c}`" for c in commits)} |')
        lines.append('')
        if notable:
            lines.append(f'**세션 요약:** {notable}')
            lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 2. EAG 승인 목록')
        lines.append('')
        if eag_gates:
            for g in eag_gates:
                lines.append(f'- {g}')
        else:
            lines.append('없음')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 3. 시스템 변경 내역')
        lines.append('')
        if changes:
            for c in changes:
                lines.append(f'- {c}')
        else:
            lines.append('없음')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 4. 인시던트')
        lines.append('')
        if incidents:
            for inc in incidents:
                lines.append(f'- {inc}')
        else:
            lines.append('없음')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 5. OI 관찰 및 신규 등록')
        lines.append('')
        if oi_obs:
            for oi in oi_obs:
                lines.append(f'- {oi}')
        else:
            lines.append('없음')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 6. 캐디 자기 보고')
        lines.append('')
        if self_rep:
            for s in self_rep:
                lines.append(f'- {s}')
        else:
            lines.append('없음')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 7. 안정화 지표')
        lines.append('')
        if stab:
            lines.append('| 지표 | 결과 |')
            lines.append('|------|------|')
            for k, v in stab.items():
                lines.append(f'| {k} | {v} |')
        else:
            lines.append('기록 없음')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 8. 에이전트 포커스')
        lines.append('')
        if agent_focus:
            lines.append('| 에이전트 | 활동 |')
            lines.append('|---------|------|')
            for agent, activity in agent_focus.items():
                lines.append(f'| {agent} | {activity} |')
        else:
            lines.append('기록 없음')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append('## 9. 이월 항목 (next_steps)')
        lines.append('')
        if next_steps:
            for i, step in enumerate(next_steps, 1):
                lines.append(f'{i}. {step}')
        else:
            lines.append('없음')
        lines.append('')
        lines.append('---')
        lines.append('')

        lines.append(f'*자동 생성 | SSOT: SESSION_CONTEXT_S{n}_FINAL.json | EAG-S291-SESSION-REPORT-AUTO-001*')
        lines.append('')

        content = '\n'.join(lines)
        out_path.write_text(content, encoding='utf-8')
        print(f'[OK] step_5_session_report: {out_path.name} ({out_path.stat().st_size} bytes)')

    except Exception as e:
        print(f'[WARN] step_5_session_report 생성 실패 (SESSION CLOSE 계속): {e}')

# ── S432 신규: 세션 자책 기록 -> failure_memory 적재 (채륄5) ──────
# EAG-S432-CH5-INGEST-IMPL-001

SELF_FAILURE_SOURCE = 'session_close'

_INCIDENT_DESIGN_RE = re.compile(r'^(D[1-9]\d?)\s*[:：]')

_INCIDENT_KEYWORDS = (
    ('타임아웃', 'SELF-TIMEOUT'),
    ('응답 절단', 'SELF-BTB-HANDOFF'),
    ('분할', 'SELF-BTB-HANDOFF'),
    ('회귀', 'SELF-REGRESSION'),
    ('파라미터', 'SELF-TOOL-PARAM'),
    ('HTTP 400', 'SELF-TOOL-PARAM'),
    ('재발', 'SELF-RECURRENCE'),
)

_NEG_KEYWORDS = (
    ('정보', 'SELF-NEG-INFO'),
    ('누락', 'SELF-NEG-OMIT'),
    ('순서', 'SELF-NEG-ORDER'),
    ('오산', 'SELF-NEG-COUNT'),
    ('건수', 'SELF-NEG-COUNT'),
    ('추측', 'SELF-NEG-GUESS'),
    ('오진단', 'SELF-NEG-MISDIAG'),
)


def _self_failure_code(text: str, origin: str) -> str:
    """자연어 자책 문장 -> 고정 error_code. 미등록은 문장 해시로 수렴한다."""
    t = (text or '').strip()
    if origin == 'incidents':
        m = _INCIDENT_DESIGN_RE.match(t)
        if m:
            return 'SELF-DESIGN-' + m.group(1).upper()
        for kw, code in _INCIDENT_KEYWORDS:
            if kw in t:
                return code
        return 'SELF-UNKNOWN-' + hashlib.sha256(t.encode('utf-8')).hexdigest()[:8]
    body = t
    if body.upper().startswith('NEG:'):
        body = body[4:].strip()
    for kw, code in _NEG_KEYWORDS:
        if kw in body:
            return code
    return 'SELF-NEG-UNKNOWN-' + hashlib.sha256(body.encode('utf-8')).hexdigest()[:8]


def ingest_self_failures(sc: dict, n: int) -> None:
    """단계III-2.5: caddy_governance_record_s{n}의 incidents / caddy_self_report(NEG)를
    area_15 failure_memory에 적재한다. POS는 적재하지 않는다.
    - 세션 내 동일 error_code는 1건으로 축약하되 occurrences로 원본 건수 보존.
    - CLOSE 재실행 시 동일 (session, error_code) 선재적분은 SKIP.
    - 어떤 경우에도 예외를 올리지 않는다(CLOSE 중단 금지).
    EAG: EAG-S432-CH5-INGEST-IMPL-001
    """
    try:
        _r = str(Path(__file__).resolve().parents[2])
        if _r not in sys.path:
            sys.path.insert(0, _r)
        from tools.governance import area_15_failure_memory as a15

        gov = sc.get('caddy_governance_record_s%d' % n) or {}
        incidents = [x for x in (gov.get('incidents') or [])
                     if isinstance(x, str) and x.strip()]
        negs = [x for x in (gov.get('caddy_self_report') or [])
                if isinstance(x, str) and x.strip().upper().startswith('NEG:')]
        if not incidents and not negs:
            print('[SKIP] ingest_self_failures: 대상 없음')
            return

        session_key = str(n)
        existing = set()
        for e in a15._load_all_entries():
            ctx = e.get('context') or {}
            if ctx.get('session_report') is True and a15._entry_session(e) == session_key:
                existing.add(e.get('error_code'))

        groups = {}
        for origin, rc, items in (('incidents', a15.FailureCategory.RC2, incidents),
                                  ('neg', a15.FailureCategory.RC1, negs)):
            for raw in items:
                code = _self_failure_code(raw, origin)
                g = groups.get(code)
                if g is None:
                    groups[code] = {'rc': rc, 'origin': origin,
                                    'text': raw.strip(), 'count': 1}
                else:
                    g['count'] += 1

        recorded = 0
        skipped = 0
        for code, g in groups.items():
            if code in existing:
                skipped += 1
                continue
            a15.record_failure(
                category=g['rc'],
                component='caddy',
                error_code=code,
                description=g['text'][:500],
                context={
                    'session':        session_key,
                    'session_report': True,
                    'source':         SELF_FAILURE_SOURCE,
                    'origin':         g['origin'],
                    'occurrences':    g['count'],
                },
                actor='caddy',
            )
            recorded += 1
        print('[SELF-FAILURE-INGEST] {"session": %d, "codes": %d, "recorded": %d, "skipped": %d}'
              % (n, len(groups), recorded, skipped))
    except Exception as e:
        print('[WARN] ingest_self_failures 실패 (SESSION CLOSE 계속): %s' % e)


# ── S273 신규: Step 5.5 Freeze Sync ──────────────────────────────

def step_5_5_freeze_sync() -> str:
    """
    session_journal.jsonl 마지막 entry의 entry_hash를 추출하여
    tests/test_goal1_freeze.py FROZEN_JOURNAL_LAST_ENTRY_HASH를 갱신.
    freeze_sync_report.json 생성.
    반환: 새 hash 문자열
    """
    if not JOURNAL_PATH.exists():
        print('[FAIL] step_5.5: session_journal.jsonl 없음')
        sys.exit(1)

    last_entry = None
    with open(JOURNAL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                last_entry = json.loads(line)

    if last_entry is None:
        print('[FAIL] step_5.5: session_journal.jsonl 비어 있음')
        sys.exit(1)

    new_hash = last_entry.get('entry_hash', '')
    if not new_hash:
        print('[FAIL] step_5.5: entry_hash 필드 없음')
        sys.exit(1)

    freeze_test_content = FREEZE_TEST_PATH.read_text(encoding='utf-8')

    import re as _re
    pattern = _re.compile(
        r'(FROZEN_JOURNAL_LAST_ENTRY_HASH\s*=\s*\(\s*\")[0-9a-f]+\"(\s*\))',
        _re.MULTILINE
    )
    match = pattern.search(freeze_test_content)
    if not match:
        print('[FAIL] step_5.5: FROZEN_JOURNAL_LAST_ENTRY_HASH 패턴 미발견')
        sys.exit(1)

    old_hash = match.group(0).split('"')[1]

    if old_hash == new_hash:
        print(f'[OK] step_5.5: hash 동일 — 갱신 불필요 ({new_hash[:16]}...)')
        report = {
            'status': 'SKIPPED',
            'reason': 'hash identical',
            'old_hash': old_hash,
            'new_hash': new_hash,
            'updated_at': _now(),
        }
        with open(FREEZE_SYNC_REPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return new_hash

    result = subprocess.run(
        ['sed', '-i',
         f's/{old_hash}/{new_hash}/',
         str(FREEZE_TEST_PATH)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f'[FAIL] step_5.5: sed 실행 실패 — {result.stderr}')
        sys.exit(1)

    print(f'[OK] step_5.5: FROZEN_JOURNAL_LAST_ENTRY_HASH 갱신')
    print(f'     old: {old_hash}')
    print(f'     new: {new_hash}')

    report = {
        'status': 'UPDATED',
        'old_hash': old_hash,
        'new_hash': new_hash,
        'updated_at': _now(),
    }
    with open(FREEZE_SYNC_REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'[OK] step_5.5: freeze_sync_report.json 생성')

    return new_hash


# ── S273 신규: Step 5.6 Freeze Verification ──────────────────────

def step_5_6_freeze_verification():
    """
    govdoc_freeze_gate.py 즉시 실행.
    PASS: 계속 / FAIL: REPORT & WAIT (sys.exit(1))
    """
    result = subprocess.run(
        [sys.executable, str(FREEZE_GATE_SCRIPT)],
        capture_output=True, text=True,
        cwd=str(ROOT)
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print('[FAIL] step_5.6: Freeze Verification FAIL — CLOSE 중단 (FAIL_CLOSED)')
        print('[FAIL] REPORT & WAIT: 비오님께 즉시 보고하십시오.')
        sys.exit(1)
    print('[OK] step_5.6: Freeze Verification PASS — CLOSE SUCCESS 조건 충족')


# ── S273 신규: close_manifest.json 생성 (run_script 대체) ─────────

def build_close_manifest(n: int, chain_tip: str, computed_hash: str) -> dict:
    """
    5개 파일의 존재·크기·SHA256을 기록한 manifest 생성.
    Caddy가 MCP read_file로 검증 가능 — run_script 의존 제거.
    """
    files_to_verify = [
        ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json',
        ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json',
        ROOT / 'SESSION_CONTEXT.json',
        ROOT / 'SESSION_CONTEXT_POINTER.json',
        ROOT / 'SESSION_CONTEXT_STALE_MANIFEST.json',
    ]

    manifest_entries = []
    all_ok = True
    for fp in files_to_verify:
        if not fp.exists() or fp.stat().st_size == 0:
            all_ok = False
            manifest_entries.append({
                'file': fp.name,
                'exists': fp.exists(),
                'size_bytes': fp.stat().st_size if fp.exists() else 0,
                'sha256': None,
                'status': 'MISSING_OR_EMPTY',
            })
        else:
            manifest_entries.append({
                'file': fp.name,
                'exists': True,
                'size_bytes': fp.stat().st_size,
                'sha256': _sha256_file(fp),
                'status': 'OK',
            })

    manifest = {
        'schema': 'close_manifest_v1',
        'session': n,
        'chain_tip': chain_tip,
        'context_hash': computed_hash,
        'generated_at': _now(),
        'all_files_ok': all_ok,
        'files': manifest_entries,
        'verification_method': 'MCP read_file OBSERVE',
    }

    with open(CLOSE_MANIFEST_PATH, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    status = 'OK' if all_ok else 'FAIL'
    print(f'[{status}] close_manifest.json 생성 ({len(manifest_entries)}개 파일 기록)')
    return manifest


# ── S276 신규: Step 5.7 Jeni Session Context 생성 ─────────────────

def step_5_7_jeni_session_context(sc: dict, n: int) -> str:
    """
    SESSION_CONTEXT_S{n}_FINAL.json 기반으로
    외부 제니 부팅용 통합 세션 컨텍스트 JENI_SESSION_CONTEXT_S{n+1}.md 생성.
    [S283 개정] UNIVERSAL(범용) + SESSION(세션별) 통합 단일 파일 생성.
    저장 경로: tools/design/JENI_SESSION_CONTEXT_S{n+1}.md
    반환: 생성된 파일 경로 문자열
    """
    chain_tip  = sc.get('chain', {}).get('tip', 'unknown')
    pytest_st  = sc.get('pytest_status', {})
    p_failed   = pytest_st.get('total_failed', '?')
    p_passed   = pytest_st.get('total_passed', '?')
    p_skipped  = pytest_st.get('total_skipped', '?')
    p_session  = pytest_st.get('last_run_session', '?')
    p_note     = pytest_st.get('note', '')

    reentry    = sc.get('session_reentry', {})
    resume     = reentry.get('resume_point', '')
    eag_co     = reentry.get('eag_carryover', '')

    next_steps  = sc.get('next_steps', [])
    agent_focus = sc.get('agent_focus', {})

    sys_changes_key = f'system_changes_s{n}'
    sys_changes = sc.get(sys_changes_key, {})
    eag_chain   = sys_changes.get('eag_chain', '없음')
    changes     = sys_changes.get('changes', [])
    commits     = sys_changes.get('commits', [])

    gov_key   = f'caddy_governance_record_s{n}'
    gov_rec   = sc.get(gov_key, {})
    incidents = gov_rec.get('incidents', [])

    oi_items  = [s for s in next_steps if 'OI-S' in s]
    eag_items = [s for s in next_steps if 'EAG-' in s]

    aif   = sc.get('aif_v1_definition', {})
    areas = aif.get('areas', {})

    now_str = _today()

    lines = []

    # ── PART 1: UNIVERSAL (범용, 불변 섹션) ──────────────────────────
    lines.append(f"# AIBA — JENI 외부 세션 컨텍스트 S{n + 1}")
    lines.append("")
    lines.append(f"생성 시각: {now_str} | 기준 SSOT: SESSION_CONTEXT_S{n}_FINAL.json")
    lines.append("")
    lines.append("> 이 문서는 외부 제니(Gemini API 직접) 세션 시작 시 채팅창에 주입하는 통합 컨텍스트입니다.")
    lines.append("> UNIVERSAL(범용) + SESSION(세션별) 섹션이 통합되어 있습니다.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## [PART 1] 제니 정체성 및 역할")
    lines.append("")
    lines.append("제니(Jeni)는 AIBA 프로젝트의 거버넌스 감사자(Governance Auditor / CRO)입니다.")
    lines.append("역할: Fail-Closed 검증, Rule 위반 탐지, 설계 감사, 증거 기반 판정.")
    lines.append("검증과 감사만 수행하며, 설계 권한(도미) 및 EAG 승인 권한(비오님)은 없습니다.")
    lines.append("")
    lines.append("| 에이전트 | 역할 | 모델 |")
    lines.append("|---|---|---|")
    lines.append("| 비오(Joshua) | CEO / EAG 최종 승인자 / Veto Holder | Human |")
    lines.append("| 도미 | CSO / 설계 전담 | OpenAI |")
    lines.append("| 제니 | CRO / 거버넌스 감사 | Gemini |")
    lines.append("| 캐디 | COO / 구현 전담 | Claude |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## [PART 1] 거버넌스 체계")
    lines.append("")
    lines.append("**DEP v1.2 체인:**")
    lines.append("도미 [DESIGN] → 캐디 IMPLEMENTABLE 검토 → 제니 TRUST_READY → 비오님 EAG → 캐디 실행")
    lines.append("")
    lines.append("**Guardian Budget + Veto 모델 (S282~):**")
    lines.append("- 비오님 = 감독자(Veto Holder). 매 실행 승인자 아님.")
    lines.append("- WF-05 자율 루프: wf05_guardian.py(port 8450)가 운영 윈도우 + Budget 검증 후 approval_id 발급.")
    lines.append("- 2-of-3 합의: 도미 설계 + 제니 검증 + 캐디 실행. 단독 완결 불가.")
    lines.append("- 비오님 Veto: 언제든 WF05_PAUSE 발행으로 전체 정지 가능.")
    lines.append("")
    lines.append("**FROZEN_HASHES:** govdoc_freeze_gate.py — 동결 파일 무결성 검증.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## [PART 1] 판정 형식 및 기준")
    lines.append("")
    lines.append("검증 출력 형식:")
    lines.append("```")
    lines.append("[JENI VERIFICATION]")
    lines.append("TRUST_READY = TRUST_READY | TRUST_ADVISORY | TRUST_NOT_READY")
    lines.append("REVALIDATION_REQUIRED = YES | NO")
    lines.append("STOP_SIGNAL = ON | OFF")
    lines.append("FAIL_REASON = (사유, 없으면 NONE)")
    lines.append("```")
    lines.append("")
    lines.append("| 판정 | 의미 |")
    lines.append("|------|------|")
    lines.append("| TRUST_READY | 거버넌스 위반 없음. 즉시 구현 가능. |")
    lines.append("| TRUST_ADVISORY | 우려 있으나 즉각 차단 불필요. 추가 근거 제시 후 상향 가능. |")
    lines.append("| TRUST_NOT_READY | 구체적 가드레일 위반 확인. 즉각 차단. 재설계 필요. |")
    lines.append("")
    lines.append("**판정 금지 사항:**")
    lines.append("- 철학적 원칙만으로 TRUST_NOT_READY 판정 금지 (실측 근거 필수)")
    lines.append("- RESOLVED/CLOSED 항목으로 현재 판단 편향 금지")
    lines.append("- 설계 권한(도미) 및 EAG 승인권(비오님) 대행 금지")
    lines.append("")
    lines.append("증거 수준 표기: RAW(직접 읽음) / INFERRED(추측) / REPORTED(전달받음)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## [PART 1] AIF v1.3 구현 현황")
    lines.append("")
    lines.append("| Area | 명칭 | 상태 |")
    lines.append("|------|------|------|")
    completed = {'area_3', 'area_8', 'area_9', 'area_12'}
    for area_key, area_name in areas.items():
        if area_key in completed:
            s = '**완료**'
        elif area_key == 'area_10':
            s = '진행 중'
        else:
            s = '미착수'
        lines.append(f"| {area_key} | {area_name} | {s} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## [PART 1] VPS 인프라")
    lines.append("")
    lines.append("| 항목 | 값 |")
    lines.append("|------|---|")
    lines.append("| host | 159.203.125.1 (NYC3, Basic 4vCPU/8GB) |")
    lines.append("| project_root | `/opt/arss/engine/arss-protocol/` |")
    lines.append("| aiba-mcp-bridge | port 8443 |")
    lines.append("| aiba-domi-runtime | port 8448 (OpenAI) |")
    lines.append("| aiba-jeni-runtime | port 8447 (Gemini / 내부 제니) |")
    lines.append("| aiba-exec-runtime | port 8449 |")
    lines.append("| aiba-wf05-guardian | port 8450 (Guardian Control Plane, S282~) |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── PART 2: SESSION (세션별 갱신 섹션) ───────────────────────────
    lines.append("## [PART 2] 현재 세션 상태")
    lines.append("")
    lines.append("| 항목 | 값 |")
    lines.append("|------|---|")
    lines.append(f"| current_session | S{n + 1} |")
    lines.append(f"| chain.tip | `{chain_tip}` |")
    lines.append(f"| pytest | {p_failed} failed / {p_passed} passed / {p_skipped} skipped |")
    lines.append(f"| pytest 기준 세션 | S{p_session} |")
    if p_note:
        lines.append(f"| pytest 비고 | {p_note} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## [PART 2] 직전 세션 요약")
    lines.append("")
    lines.append(f"**resume_point**: {resume}")
    lines.append("")
    if eag_co:
        lines.append(f"**eag_carryover**: {eag_co}")
        lines.append("")
    if commits:
        lines.append(f"**commits**: {', '.join(commits)}")
        lines.append("")
    if changes:
        lines.append(f"**S{n} 변경 내역**:")
        for c in changes:
            lines.append(f"- {c}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## [PART 2] Active EAG")
    lines.append("")
    lines.append(f"EAG chain (S{n}): {eag_chain}")
    lines.append("")
    if eag_items:
        lines.append("**이월 EAG 항목**:")
        for e in eag_items:
            lines.append(f"- {e}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## [PART 2] Active OI (Open Issues)")
    lines.append("")
    if oi_items:
        for o in oi_items:
            lines.append(f"- {o}")
    else:
        lines.append("없음")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## [PART 2] S{n + 1} Next Steps")
    lines.append("")
    for i, step in enumerate(next_steps, 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## [PART 2] 최근 세션 인시던트 — S{n}")
    lines.append("")
    if incidents:
        for inc in incidents:
            lines.append(f"- {inc}")
    else:
        lines.append("없음")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## [PART 2] 에이전트 포커스 — S{n} 마감 기준")
    lines.append("")
    lines.append("| 에이전트 | 상태 |")
    lines.append("|---------|------|")
    for agent, status in agent_focus.items():
        lines.append(f"| {agent} | {status} |")
    lines.append("")

    content = "\n".join(lines) + "\n"

    out_dir  = ROOT / JENI_SESSION_CONTEXT_SUBDIR
    out_path = out_dir / f'JENI_SESSION_CONTEXT_S{n + 1}.md'
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'[OK] step_5.7: JENI_SESSION_CONTEXT_S{n + 1}.md (UNIVERSAL+SESSION 통합) 생성 → {out_path}')
    return str(out_path)


# ── 기존 함수들 (원본 유지) ───────────────────────────────────────

def identify_archive_candidates(sc: dict, n: int, N: int = N_RETENTION) -> dict:
    threshold = n - N + 1
    candidates = {}
    for k, v in sc.items():
        m = _RECORD_KEY_RE.match(k)
        if m and int(m.group(2)) < threshold:
            candidates[k] = v
        elif k in GROUP_D_MIGRATE_WHITELIST:
            candidates[k] = v
    return candidates


def verify_archive_integrity(archive_path: Path, candidates: dict) -> bool:
    try:
        with open(archive_path, encoding='utf-8') as f:
            written = json.load(f)
    except Exception as e:
        print(f'[INTEGRITY-FAIL] archive 재읽기 오류: {e}')
        return False
    data = written.get('data', {})
    for k, v in candidates.items():
        if k not in data or data[k] != v:
            print(f'[INTEGRITY-FAIL] 키 누락/불일치: {k}')
            return False
    return True


def load_delta(delta_json_path: str) -> dict:
    try:
        with open(delta_json_path, encoding='utf-8') as f:
            delta = json.load(f)
    except FileNotFoundError:
        print(f'[FAIL] delta-json 파일 없음: {delta_json_path}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'[FAIL] delta-json JSON decode 실패: {e}')
        sys.exit(1)

    for key, expected_type in DELTA_REQUIRED_KEYS.items():
        if key not in delta:
            print(f'[FAIL] delta-json 필수 키 누락: {key}')
            sys.exit(1)
        if not isinstance(delta[key], expected_type):
            print(f'[FAIL] delta-json 타입 불일치: {key} '
                  f'(expected {expected_type.__name__}, '
                  f'got {type(delta[key]).__name__})')
            sys.exit(1)
    return delta


def load_prev_final(n: int) -> dict:
    prev_path = ROOT / f'SESSION_CONTEXT_S{n - 1}_FINAL.json'
    try:
        with open(prev_path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f'[FAIL] S{n - 1}_FINAL 파일 없음: {prev_path}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'[FAIL] S{n - 1}_FINAL JSON decode 실패: {e}')
        sys.exit(1)


def apply_delta(sc: dict, n: int, chain_tip: str, prev_tip: str, delta: dict):
    now = _now()
    sc['session_count'] = n
    sc['chain'] = {'session': n, 'prev_tip': prev_tip, 'tip': chain_tip}
    sc['updated_at'] = now
    sc['generated_at'] = now
    sc['session_reentry']                   = delta['session_reentry']
    sc['next_steps']                        = delta['next_steps']
    sc['agent_focus']                       = delta['agent_focus']
    sc['pytest_status']                     = delta['pytest_status']
    sc[f'system_changes_s{n}']              = delta['system_changes']
    sc[f'caddy_governance_record_s{n}']     = delta['caddy_governance_record']
    sc[f'visibility_metrics_s{n}']          = delta['visibility_metrics']
    sc['session_delta']                     = delta['session_delta']
    sc['sync_meta']                         = delta['sync_meta']
    # EAG-S405-BOOT-DIET-ARCHIVE-001: system_changes_s -> _RECORD_KEY_RE archive path. pop removed.
    # Always-On Phase 1: review_schedule init/preserve (EAG-S324-REVIEW-SCHEDULE-001)
    if 'review_schedule' not in sc:
        _now_kst = datetime.now(KST)
        _next_week  = (_now_kst + timedelta(days=7)).strftime('%Y-%m-%d')
        _next_month = (_now_kst.replace(day=28) + timedelta(days=4)).replace(day=1).strftime('%Y-%m-%d')
        sc['review_schedule'] = {
            'weekly_failure_audit':         {'last_run': None, 'next_due': _next_week},
            'monthly_assumption_review':     {'last_run': None, 'next_due': _next_month},
            'quarterly_constitution_review': {'last_run': None, 'next_due': '2026-10-01'},
        }
        print('[OK] review_schedule init (Always-On Phase 1, EAG-S324-REVIEW-SCHEDULE-001)')

    # --- [EAG-S385] review_schedule completion (add-only) ---
    _completed = delta.get('review_completed') or []
    _rs = sc.get('review_schedule')
    if isinstance(_completed, list) and _completed and isinstance(_rs, dict):
        _k = datetime.now(KST)
        _m1 = (_k.replace(day=28) + timedelta(days=4)).replace(day=1)
        _m2 = (_m1.replace(day=28) + timedelta(days=4)).replace(day=1)
        _m3 = (_m2.replace(day=28) + timedelta(days=4)).replace(day=1)
        _due = {
            'weekly_failure_audit':          (_k + timedelta(days=7)).strftime('%Y-%m-%d'),
            'monthly_assumption_review':     _m1.strftime('%Y-%m-%d'),
            'quarterly_constitution_review': _m3.strftime('%Y-%m-%d'),
        }
        _today = _k.strftime('%Y-%m-%d')
        for _rt in _completed:
            if _rt in _due and isinstance(_rs.get(_rt), dict):
                _rs[_rt]['last_run'] = _today
                _rs[_rt]['next_due'] = _due[_rt]
                print('[OK] review_schedule completed: %s -> last_run=%s next_due=%s (EAG-S385)' % (_rt, _today, _due[_rt]))
    archive_candidates = identify_archive_candidates(sc, n)
    return sc, archive_candidates


def build_archive(n: int, archive_candidates: dict) -> dict:
    prev_archive_path = ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n - 1}.json'
    try:
        with open(prev_archive_path, encoding='utf-8') as f:
            prev_arch = json.load(f)
        total_tier_d = prev_arch.get('_archive_meta', {}).get('total_tier_d_keys', 78)
    except FileNotFoundError:
        print(f'[FAIL] S{n - 1} ARCHIVE 파일 없음: {prev_archive_path}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'[FAIL] S{n - 1} ARCHIVE JSON decode 실패: {e}')
        sys.exit(1)

    migrated = len(archive_candidates)
    return {
        '_archive_meta': {
            'archive_session':    n,
            'archive_date':       _today(),
            'base_archive':       f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n - 1}.json',
            'tier_d_change':      f'+{migrated} keys migrated' if migrated else '변동 없음',
            'migrated_keys_count': migrated,
            'total_tier_d_keys':  total_tier_d + migrated,
        },
        'data': archive_candidates,
    }


def run_verify(n: int, expected_chain: str, expected_hash: str) -> None:
    errors = []
    files = [
        ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json',
        ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json',
        ROOT / 'SESSION_CONTEXT.json',
        ROOT / 'SESSION_CONTEXT_POINTER.json',
        ROOT / 'SESSION_CONTEXT_STALE_MANIFEST.json',
    ]
    for fp in files:
        if not fp.exists():
            errors.append(f'MISSING: {fp.name}')
        elif fp.stat().st_size == 0:
            errors.append(f'EMPTY: {fp.name}')
        else:
            print(f'[OK] {fp.name} ({fp.stat().st_size} bytes)')

    try:
        with open(ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json', encoding='utf-8') as f:
            sc = json.load(f)
        if sc.get('session_count') != n:
            errors.append(f'session_count: {sc.get("session_count")} != {n}')
        else:
            print(f'[OK] session_count == {n}')
        if sc.get('chain', {}).get('tip') != expected_chain:
            errors.append(f'chain.tip mismatch')
        else:
            print(f'[OK] chain.tip == {expected_chain}')
        if sc.get('context_hash') != expected_hash:
            errors.append('SC_FINAL.context_hash mismatch')
        else:
            print(f'[OK] SC_FINAL.context_hash == {expected_hash[:16]}...')
        with open(ROOT / 'SESSION_CONTEXT_POINTER.json', encoding='utf-8') as f:
            ptr = json.load(f)
        if ptr.get('current_session') != n:
            errors.append(f'POINTER.current_session mismatch')
        else:
            print(f'[OK] POINTER.current_session == {n}')
        if ptr.get('chain_tip') != expected_chain:
            errors.append(f'POINTER.chain_tip mismatch')
        else:
            print(f'[OK] POINTER.chain_tip == {expected_chain}')
        if ptr.get('context_hash') != expected_hash:
            errors.append('POINTER.context_hash mismatch')
        else:
            print(f'[OK] POINTER.context_hash 일치')
        with open(ROOT / 'SESSION_CONTEXT_STALE_MANIFEST.json', encoding='utf-8') as f:
            mf = json.load(f)
        if mf.get('context_hash') != expected_hash:
            errors.append('MANIFEST.context_hash mismatch')
        else:
            print(f'[OK] MANIFEST.context_hash 일치')
    except Exception as e:
        errors.append(f'VERIFY 읽기 오류: {e}')

    print()
    if errors:
        print(f'VERIFICATION FAILED — {len(errors)} error(s)')
        for e in errors:
            print(f'  >> {e}')
        sys.exit(1)
    else:
        print('VERIFICATION PASSED: ALL CHECKS OK')



# ── IAPG-III Phase1.5 (S356) 계약14 갈래 A — validate_bundle ──────────────

def _normalized_context_hash_for_bundle(path):
    """SC_FINAL 정규화 hash 재계산 (pointer_manager._compute_context_hash 동치)."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        payload = {k: v for k, v in data.items() if k != 'context_hash'}
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(serialized).hexdigest()
    except Exception:
        return None


def validate_bundle(session, expected_hash, pointer, manifest, final_path):
    """
    IAPG-III 계약14 (갈래 A 최소 스키마) — 4축 bundle 정합 검증.
    갈래 B(context_writer/close_bundle_validator)는 대상 아님.
    반환: (is_ok: bool, errors: list[str]). 불일치 시 NONE_SYNC fail-closed.
    EAG: EAG-S356-IAPG-PHASE15-IMPL-002
    """
    errors = []
    fp = Path(final_path)
    if pointer.get('current_session') != session:
        errors.append(f"NONE_SYNC:SESSION(pointer={pointer.get('current_session')}!={session})")
    if manifest.get('session_count') != session:
        errors.append(f"NONE_SYNC:SESSION(manifest={manifest.get('session_count')}!={session})")
    if pointer.get('context_hash') != expected_hash:
        errors.append("NONE_SYNC:HASH(pointer!=expected)")
    if manifest.get('context_hash') != expected_hash:
        errors.append("NONE_SYNC:HASH(manifest!=expected)")
    if pointer.get('generated_at') != manifest.get('updated_at'):
        errors.append(
            f"NONE_SYNC:TIMESTAMP(pointer.generated_at={pointer.get('generated_at')}"
            f"!=manifest.updated_at={manifest.get('updated_at')})"
        )
    if not fp.exists():
        errors.append(f"NONE_CONTENT:FINAL_MISSING({fp.name})")
    else:
        recomputed = _normalized_context_hash_for_bundle(fp)
        if recomputed is None:
            errors.append(f"NONE_CONTENT:FINAL_UNREADABLE({fp.name})")
        elif recomputed != expected_hash:
            errors.append("NONE_CONTENT:FINAL_HASH_MISMATCH")
    return (len(errors) == 0, errors)


# ── main ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='SESSION CLOSE 5-file 번들 생성 도구 (S276 개정)'
    )
    parser.add_argument('--session',     type=int, required=True)
    parser.add_argument('--chain-tip',   required=True)
    parser.add_argument('--prev-tip',    required=True)
    parser.add_argument('--delta-json',  required=True)
    parser.add_argument('--dry-run',     action='store_true')
    parser.add_argument('--approval-id', default='')
    parser.add_argument('--ceiling-override', action='store_true')
    args = parser.parse_args()

    os.umask(0o027)

    n         = args.session
    chain_tip = args.chain_tip
    prev_tip  = args.prev_tip

    delta = load_delta(args.delta_json)
    sc = load_prev_final(n)
    sc, archive_candidates = apply_delta(sc, n, chain_tip, prev_tip, delta)

    if args.dry_run:
        sc_sim = dict(sc)
        for k in archive_candidates:
            sc_sim.pop(k, None)
        sim_hash = _context_hash(sc_sim)
        print(f'[DRY-RUN] 산출 예정: SESSION_CONTEXT_S{n}_FINAL.json')
        print(f'[DRY-RUN]   session_count  = {n}')
        print(f'[DRY-RUN]   chain_tip      = {chain_tip}')
        print(f'[DRY-RUN]   context_hash   = {sim_hash}')
        print(f'[DRY-RUN] [③] Tier D 이관 대상 = {len(archive_candidates)}개')
        print(f'[DRY-RUN] S273 추가: Step 5.5 Freeze Sync + Step 5.6 Freeze Verification')
        print(f'[DRY-RUN] S273 추가: close_manifest.json (run_script 대체)')
        print(f'[DRY-RUN] S276 추가: Step 5.7 JENI_SESSION_CONTEXT_S{n + 1}.md 생성')
        sys.exit(0)

    if not args.approval_id or not _validate_approval_id(args.approval_id):
        print('[FAIL] --approval-id 미제공 또는 형식 불일치')
        sys.exit(1)

    # ── C7-1: 롤백 경로 딕셔너리 (단계별 _rollback_all 참조용)
    n_val = n  # 클로저 캡처용
    rollback_paths: dict = {}  # 파일 기록 시마다 등록

    # ════════════════════════════════════════════════════════
    # 단계 I: 번들 대상 파일 순차 기록 (POINTER 제외)
    # C7-1 순서: ARCHIVE -> SC_FINAL -> canonical -> MANIFEST
    # ════════════════════════════════════════════════════════

    # ── I-1: ARCHIVE 기록 + 무결성 검증
    archive_path = ROOT / f'SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json'
    rollback_paths['archive'] = archive_path
    try:
        archive = build_archive(n, archive_candidates)
        with open(archive_path, 'w', encoding='utf-8') as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT_ARCHIVE_TIER_D_S{n}.json')
    except SystemExit:
        raise
    except Exception as e:
        print(f'[FAIL] ARCHIVE 기록 실패: {e}')
        sys.exit(1)

    if not verify_archive_integrity(archive_path, archive_candidates):
        _rollback_all(1, rollback_paths)
        print('[FAIL] archive 무결성 검증 실패 — FAIL_CLOSED')
        sys.exit(1)

    for k in archive_candidates:
        sc.pop(k, None)
    migrated = len(archive_candidates)
    print(f'[OK] active pop 확정 — migrated {migrated} keys')

    canon = len([k for k in sc.keys() if k not in CANONICAL_EXCLUDE_KEYS])
    if canon > CEILING_LIMIT and not args.ceiling_override:
        print(f'[FAIL] canonical key {canon} > 천장 {CEILING_LIMIT} — HARD_STOP')
        sys.exit(1)
    elif canon >= 41:
        print(f'[SYSTEM_REVIEW] canonical key {canon} — 천장 임박')
    else:
        print(f'[OK] canonical key {canon} <= 천장 {CEILING_LIMIT}')

    sc['context_hash'] = _context_hash(sc)
    computed_hash = sc['context_hash']

    # ── I-2: SC_FINAL 저장
    sc_final_path = ROOT / f'SESSION_CONTEXT_S{n}_FINAL.json'
    rollback_paths['sc_final'] = sc_final_path
    try:
        with open(sc_final_path, 'w', encoding='utf-8') as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT_S{n}_FINAL.json')
    except Exception as e:
        print(f'[FAIL] SC_FINAL 저장 실패: {e}')
        sys.exit(1)

    # ── I-3: canonical overwrite
    sc_canonical_path = ROOT / 'SESSION_CONTEXT.json'
    rollback_paths['canonical'] = sc_canonical_path
    try:
        with open(sc_canonical_path, 'w', encoding='utf-8') as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT.json canonical overwrite')
    except Exception as e:
        _rollback_all(3, rollback_paths)
        print(f'[FAIL] SESSION_CONTEXT.json overwrite 실패: {e}')
        sys.exit(1)

    # ── I-4: STALE_MANIFEST 갱신
    # [계약5] shared_ts 단일공유: POINTER.generated_at == MANIFEST.updated_at
    # shared_ts는 MANIFEST 기록 직전 1회 계산 -> POINTER 발행까지 메모리 유지 (C7-9)
    shared_ts = _now()
    manifest_path = ROOT / 'SESSION_CONTEXT_STALE_MANIFEST.json'
    rollback_paths['manifest'] = manifest_path
    try:
        manifest = {
            'session_count': sc['session_count'],
            'context_hash':  sc['context_hash'],
            'updated_at':    shared_ts,
            'status':        'FRESH',
        }
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f'[OK] SESSION_CONTEXT_STALE_MANIFEST.json')
    except Exception as e:
        _rollback_all(4, rollback_paths)
        print(f'[FAIL] STALE_MANIFEST 갱신 실패: {e}')
        sys.exit(1)

    # ════════════════════════════════════════════════════════
    # 단계 II: 번들 완결 게이트 (POINTER 발행 전 필수 통과)
    # C7-1 순서: validate_bundle -> Freeze Sync -> Freeze Verification -> close_manifest
    # ════════════════════════════════════════════════════════

    # ── II-1: validate_bundle 4축 self-check (C7-6, C7-14)
    # POINTER 미발행 상태에서 메모리의 pointer_dict를 인자로 전달 (캐디 구현검토 의견)
    pointer_path = ROOT / 'SESSION_CONTEXT_POINTER.json'
    rollback_paths['pointer'] = pointer_path
    pointer_dict = {
        'current_session': sc['session_count'],
        'canonical_file':  'SESSION_CONTEXT.json',
        'final_file':      f'SESSION_CONTEXT_S{n}_FINAL.json',
        'chain_tip':       sc['chain']['tip'],
        'prev_tip':        sc['chain']['prev_tip'],
        'context_hash':    sc['context_hash'],
        'generated_at':    shared_ts,
        'schema_version':  '4.0',
    }
    print()
    print('── 단계II-1: IAPG-III 계약14 validate_bundle (POINTER 미발행 상태) ──')
    _bundle_ok, _bundle_errors = validate_bundle(
        n, computed_hash, pointer_dict, manifest, sc_final_path
    )
    if not _bundle_ok:
        _rollback_all(4, rollback_paths)
        print(f'[FAIL] validate_bundle NONE_SYNC: {_bundle_errors}')
        print('[FAIL] CLOSE 중단 (FAIL_CLOSED). REPORT & WAIT.')
        sys.exit(1)
    print('[OK] validate_bundle: 4축 PASS (POINTER 미발행 상태 검증 완료)')

    # ── II-2: Freeze Sync (Step 5.5)
    print()
    print('── 단계II-2: S273 Step 5.5 Freeze Sync ────────────────────')
    step_5_5_freeze_sync()

    # ── II-3: Freeze Verification (Step 5.6) — C7-12: POINTER 발행 전 필수
    print()
    print('── 단계II-3: S273 Step 5.6 Freeze Verification (POINTER 발행 전) ──')
    step_5_6_freeze_verification()

    # [EAG-S395] Decision Ledger: EAG gate -> DC-3 record.
    # Placed after dry-run early exit and after the freeze fail-closed gate,
    # so a rolled-back CLOSE leaves no orphan ledger entries.
    _r = str(Path(__file__).resolve().parents[2])
    if _r not in sys.path:
        sys.path.insert(0, _r)
    from tools.close.record_eag_gates import record_eag_gates
    record_eag_gates(
        n,
        delta.get('caddy_governance_record', {}).get('eag_gates_this_session'),
        _validate_approval_id,
    )

    # ── II-4: close_manifest.json 생성
    print()
    print('── 단계II-4: S273 close_manifest.json 생성 ─────────────────')
    build_close_manifest(n, chain_tip, computed_hash)

    # ════════════════════════════════════════════════════════
    # 단계 III: 최종 원자 발행 + 사후 부수 작업
    # C7-1: POINTER 원자 발행 -> Session Report -> Jeni Context -> run_verify
    # ════════════════════════════════════════════════════════

    # ── III-1: POINTER 원자 발행 (C7-3, _atomic_write_pointer)
    # 모든 게이트 통과 후 최후 발행 — POINTER 존재 = 번들 완결 불변식 확립
    print()
    print('── 단계III-1: POINTER 원자 발행 (C7-3 atomic write) ────────')
    try:
        _atomic_write_pointer(pointer_dict, pointer_path)
    except Exception as e:
        _rollback_all(4, rollback_paths)  # POINTER 발행 실패 -> POINTER 미존재, 단계I 파일만 롤백
        print(f'[FAIL] POINTER 원자 발행 실패: {e}')
        sys.exit(1)

    # ── III-2 (사후): Session Report 생성
    print()
    print('── 단계III-2: S291 Step 5 Session Report 생성 ─────────────')
    step_5_session_report(sc, n)

    # ── III-2.5 (사후): S432 채륄5 자책 기록 적재
    print()
    print('── 단계III-2.5: S432 세션 자책 기록 -> failure_memory 적재 ──')
    ingest_self_failures(sc, n)

    # ── III-3 (사후): Jeni Session Context 생성 (Step 5.7)
    print()
    print('── 단계III-3: S276 Step 5.7 Jeni Session Context 생성 ──────')
    step_5_7_jeni_session_context(sc, n)

    # ── III-4 (사후): 3-way consistency 검증
    print()
    print('── 단계III-4: 3-way consistency verify ──────────────────────')
    run_verify(n, chain_tip, computed_hash)

    print()
    print('[CLOSE SUCCESS] 계약7 Write-Pointer-Last 완료 — POINTER 원자 발행 확인')
    sys.exit(0)


if __name__ == '__main__':
    main()
