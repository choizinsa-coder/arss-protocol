"""
test_tierd_migrate_s249.py
DEP-S249-TIERD-MIGRATE-001 (목표 ③) 검증 TC.
배포 위치: tests/test_tierd_migrate_s249.py
대상: tools/close/session_close_generator.py
"""
import json
import importlib.util
from pathlib import Path

import pytest

# 대상 모듈 동적 로드 (tools/close 경로)
_SPEC_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'close' / 'session_close_generator.py'
_spec = importlib.util.spec_from_file_location('scg_s249', _SPEC_PATH)
scg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scg)


def _mock_sc(low=215, high=249):
    sc = {
        'session_count': high,
        'goal2_declaration': {'status': 'DECLARED'},     # S250 group D 화이트리스트 → 이관 대상
        'goal2_progress': {'status': 'IN_PROGRESS'},      # S250 위험 키 → active 유지(비대상)
        'system_changes_s248': {'commits': ['x']},        # 비대상(GOV-003)
    }
    for s in range(low, high + 1):
        sc[f'caddy_governance_record_s{s}'] = {'session': s, '비고': '한글'}
        sc[f'visibility_metrics_s{s}'] = {'session': s}
    return sc


def _record_count(sc):
    return sum(1 for k in sc if scg._RECORD_KEY_RE.match(k))


# ── 식별 술어 (정착조건 a) ─────────────────────────────────────
def test_identify_predicate_boundary():
    sc = _mock_sc()
    cands = scg.identify_archive_candidates(sc, 249, N=10)  # N=10 explicit, threshold=240 (EAG-S405)
    record_cands = [k for k in cands if scg._RECORD_KEY_RE.match(k)]
    assert len(record_cands) == 50                           # s215..s239 ×2 (record 경계 불변)
    assert 'goal2_declaration' in cands                      # S250 group D 화이트리스트 이관
    assert len(cands) == 51                                  # record 50 + group D 1
    assert 'caddy_governance_record_s239' in cands           # aged
    assert 'caddy_governance_record_s240' not in cands       # 경계 유지
    assert 'visibility_metrics_s249' not in cands            # 최신 유지


def test_identify_excludes_nontargets():
    sc = _mock_sc()
    cands = scg.identify_archive_candidates(sc, 249, N=10)  # N=10 explicit (EAG-S405)
    # S250: goal2_declaration -> whitelist migration. goal2_progress -> active.
    # system_changes: EAG-S405 adds to _RECORD_KEY_RE -> test_system_changes_archivable.
    assert 'goal2_progress' not in cands
    assert 'goal2_declaration' in cands

def test_identify_nondestructive():
    sc = _mock_sc()
    before = _record_count(sc)
    scg.identify_archive_candidates(sc, 249)
    assert _record_count(sc) == before                       # sc 미변경


# ── build_archive 무손실 기록 + 카운트 (정착조건 b) ────────────
def test_build_archive_records_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(scg, 'ROOT', tmp_path)
    prev = {'_archive_meta': {'total_tier_d_keys': 78}}
    (tmp_path / 'SESSION_CONTEXT_ARCHIVE_TIER_D_S248.json').write_text(
        json.dumps(prev), encoding='utf-8')
    cands = {'caddy_governance_record_s215': {'session': 215}}
    arch = scg.build_archive(249, cands)
    assert arch['data'] == cands                              # 역조회 소스
    assert arch['_archive_meta']['migrated_keys_count'] == 1
    assert arch['_archive_meta']['total_tier_d_keys'] == 79   # 78 + 1


# ── 무결성 검증 ───────────────────────────────────────────────
def test_integrity_pass(tmp_path):
    cands = {'caddy_governance_record_s215': {'session': 215}}
    p = tmp_path / 'arch.json'
    p.write_text(json.dumps({'data': cands}), encoding='utf-8')
    assert scg.verify_archive_integrity(p, cands) is True


def test_integrity_fail_on_missing(tmp_path):
    cands = {'caddy_governance_record_s215': {'session': 215}}
    p = tmp_path / 'arch.json'
    p.write_text(json.dumps({'data': {}}), encoding='utf-8')  # 키 누락
    assert scg.verify_archive_integrity(p, cands) is False


# ── context_hash 계약 ─────────────────────────────────────────
def test_context_hash_deterministic_and_ensure_ascii():
    sc = _mock_sc()
    h1 = scg._context_hash(sc)
    h2 = scg._context_hash(dict(sc))
    assert h1 == h2 and len(h1) == 64
    raw = json.dumps(sc, sort_keys=True, ensure_ascii=False)
    assert '한글' in raw                                      # ensure_ascii=False


# ── 정량 기준: 이관 후 active record 키 ≤ 2N ───────────────────
def test_post_migration_record_cap():
    sc = _mock_sc()
    cands = scg.identify_archive_candidates(sc, 249, N=10)   # N=10 explicit (EAG-S405)
    for k in cands:
        sc.pop(k, None)
    # EAG-S405: system_changes_s248 counted by _record_count (+1)
    assert _record_count(sc) == 21                            # gov*10 + vis*10 + sys_s248 = 21
    assert _record_count(sc) <= 2 * 10 + 1                   # N=10 hardcoded ceiling


# -- EAG-S405-BOOT-DIET-ARCHIVE-001 new TCs --------------------
def test_production_n3_boundary():
    """N_RETENTION=3 boundary pin. FAIL if N changes."""
    sc = _mock_sc()
    # N=3 -> threshold=249-3+1=247
    cands = scg.identify_archive_candidates(sc, 249)  # uses N_RETENTION default=3
    # gov_s{215..246}(32) + vis_s{215..246}(32) + goal2_declaration(1) = 65
    assert len(cands) == 65
    assert 'caddy_governance_record_s246' in cands
    assert 'caddy_governance_record_s247' not in cands
    assert 'visibility_metrics_s246' in cands
    assert 'system_changes_s248' not in cands  # 248 >= 247
    for k in cands:
        sc.pop(k, None)
    # remaining: gov*3 + vis*3 + sys_s248 = 7
    assert _record_count(sc) == 7


def test_system_changes_archivable():
    """Change 2: system_changes_s* becomes archive candidate. EAG-S405"""
    sc = _mock_sc()
    sc['system_changes_s220'] = {'commits': ['test']}  # 220 < threshold=240
    cands = scg.identify_archive_candidates(sc, 249, N=10)
    assert 'system_changes_s220' in cands   # Change 2: archive candidate
    assert 'system_changes_s248' not in cands  # 248 >= 240
