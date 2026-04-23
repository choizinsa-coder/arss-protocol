import sys, os, pytest, unittest.mock as mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from recovery_manager import build_recovery_package_r1, generate_recovery_candidate_r2, validate_r2_candidate_receipt_consistency, calculate_canonical_hash

VALID_TRIGGER = {"trigger_reason":"manual_recovery","trigger_event_ref":"EVT-001","requested_by":"beo","recovery_mode":"LKG_STRICT_REPLAY"}
VALID_SELECTOR = {"lkg_receipt_id":"receipt-s49-001","lkg_receipt_hash":"aaaa"*16,"lkg_artifact_hash":"bbbb"*16,"lkg_session_count":49,"lkg_generated_at":"2026-04-21T10:00:00+00:00","lkg_selection_basis":"chain_valid_receipt","lkg_selection_verdict":"SELECTED"}
VALID_SNAPSHOT = {"session_count":49,"system_version":"v1.5"}
VALID_AUDIT = {"candidate_pool_summary":"3 candidates","rejected_candidates_summary":"2 rejected","final_selection_reason":"highest chain-valid receipt","selector_version":"v1.0"}

def make_valid_r1():
    return build_recovery_package_r1("REC-001",VALID_TRIGGER,VALID_SELECTOR,VALID_SNAPSHOT,52,VALID_AUDIT)

def test_r2_uses_r1_package_only():
    pkg = make_valid_r1()
    c, r = generate_recovery_candidate_r2(pkg)
    assert c is not None and r is not None

def test_r2_fails_when_selected_last_known_good_block_missing():
    pkg = make_valid_r1(); del pkg["selected_last_known_good"]
    with pytest.raises((ValueError, KeyError)):
        generate_recovery_candidate_r2(pkg)

def test_r2_fails_when_snapshot_block_missing():
    pkg = make_valid_r1(); del pkg["selected_last_known_good_snapshot"]
    with pytest.raises((ValueError, KeyError)):
        generate_recovery_candidate_r2(pkg)

def test_r2_fails_when_snapshot_session_count_unknown():
    bad = {**VALID_SELECTOR,"lkg_session_count":"unknown"}
    with pytest.raises((ValueError, TypeError)):
        build_recovery_package_r1("REC-BAD",VALID_TRIGGER,bad,VALID_SNAPSHOT,52,VALID_AUDIT)

def test_r2_candidate_receipt_source_fields_match():
    pkg = make_valid_r1()
    c, r = generate_recovery_candidate_r2(pkg)
    for f in ["source_lkg_receipt_id","source_lkg_receipt_hash","source_lkg_artifact_hash","source_lkg_session_count","source_package_hash"]:
        assert c[f] == r[f]
    assert r["candidate_state_hash"] == calculate_canonical_hash(c["candidate_state_payload"])
    assert r["candidate_snapshot_session_count"] == c["source_lkg_session_count"]

def test_r2_candidate_is_strict_lkg_replay():
    pkg = make_valid_r1()
    c, _ = generate_recovery_candidate_r2(pkg)
    assert c["generation_mode"] == "LKG_STRICT_REPLAY"
    assert c["candidate_state_payload"] == VALID_SNAPSHOT
    assert c["source_lkg_session_count"] == 49

def test_r2_does_not_read_current_session_context():
    pkg = make_valid_r1()
    orig = open; accessed = []
    def mock_open(path, *a, **kw): accessed.append(str(path)); return orig(path, *a, **kw)
    with mock.patch("builtins.open", side_effect=mock_open):
        generate_recovery_candidate_r2(pkg)
    assert [p for p in accessed if "SESSION_CONTEXT" in p] == []

def test_no_chain_mutation_side_effect():
    pkg = make_valid_r1(); writes = []
    orig = open
    def tracking(path, mode="r", *a, **kw):
        if any(x in str(path) for x in ["evidence/","scoring_ledger"]) and any(m in str(mode) for m in ["w","a","x"]):
            writes.append((str(path),str(mode)))
        return orig(path, mode, *a, **kw)
    with mock.patch("builtins.open", side_effect=tracking):
        generate_recovery_candidate_r2(pkg)
    assert writes == []

def test_no_session_context_overwrite():
    pkg = make_valid_r1(); writes = []
    orig = open
    def tracking(path, mode="r", *a, **kw):
        if "SESSION_CONTEXT" in str(path) and any(m in str(mode) for m in ["w","a","x"]):
            writes.append((str(path),str(mode)))
        return orig(path, mode, *a, **kw)
    with mock.patch("builtins.open", side_effect=tracking):
        generate_recovery_candidate_r2(pkg)
    assert writes == []

def test_r2_triangulation_mismatch():
    pkg = make_valid_r1()
    c, r = generate_recovery_candidate_r2(pkg)
    r["source_lkg_receipt_id"] = "WRONG_ID"; r["consistency_verdict"] = "PENDING"
    with pytest.raises(ValueError, match="Triangulation mismatch"):
        validate_r2_candidate_receipt_consistency(c, r, pkg)
