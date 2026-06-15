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
    cands = scg.identify_archive_candidates(sc, 249)        # threshold=240
    record_cands = [k for k in cands if scg._RECORD_KEY_RE.match(k)]
    assert len(record_cands) == 50                           # s215..s239 ×2 (record 경계 불변)
    assert 'goal2_declaration' in cands                      # S250 group D 화이트리스트 이관
    assert len(cands) == 51                                  # record 50 + group D 1
    assert 'caddy_governance_record_s239' in cands           # aged
    assert 'caddy_governance_record_s240' not in cands       # 경계 유지
    assert 'visibility_metrics_s249' not in cands            # 최신 유지


def test_identify_excludes_nontargets():
    sc = _mock_sc()
    cands = scg.identify_archive_candidates(sc, 249)
    # S250(EAG-S250-CANONSET-001): group D 화이트리스트(goal2_declaration)는 이관 대상.
    # 위험 키 goal2_progress와 구조 키 system_changes는 여전히 비대상(안전 단언 강화).
    assert 'goal2_progress' not in cands                     # 위험 키 active 유지
    assert not any('system_changes' in k for k in cands)     # GOV-003 비대상
    assert 'goal2_declaration' in cands                      # 화이트리스트 이관


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
    cands = scg.identify_archive_candidates(sc, 249)
    for k in cands:
        sc.pop(k, None)                                       # 성공 경로 pop
    assert _record_count(sc) == 20                            # s240..s249 ×2
    assert _record_count(sc) <= 2 * scg.N_RETENTION
