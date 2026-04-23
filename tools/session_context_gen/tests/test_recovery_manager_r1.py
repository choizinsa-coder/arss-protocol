import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from recovery_manager import build_recovery_package_r1, validate_r1_package_integrity

VALID_TRIGGER = {"trigger_reason":"manual_recovery","trigger_event_ref":"EVT-001","requested_by":"beo","recovery_mode":"LKG_STRICT_REPLAY"}
VALID_SELECTOR = {"lkg_receipt_id":"receipt-s49-001","lkg_receipt_hash":"aaaa"*16,"lkg_artifact_hash":"bbbb"*16,"lkg_session_count":49,"lkg_generated_at":"2026-04-21T10:00:00+00:00","lkg_selection_basis":"chain_valid_receipt","lkg_selection_verdict":"SELECTED"}
VALID_SNAPSHOT = {"session_count":49,"system_version":"v1.5"}
VALID_AUDIT = {"candidate_pool_summary":"3 candidates","rejected_candidates_summary":"2 rejected","final_selection_reason":"highest chain-valid receipt","selector_version":"v1.0"}

def make_valid_r1(**ov):
    kw = dict(recovery_id="REC-001",trigger_context=VALID_TRIGGER,selector_result=VALID_SELECTOR,lkg_snapshot_payload=VALID_SNAPSHOT,created_from_session=52,selection_audit=VALID_AUDIT)
    kw.update(ov); return build_recovery_package_r1(**kw)

def test_r1_package_contains_selected_last_known_good_block():
    pkg = make_valid_r1()
    assert "selected_last_known_good" in pkg
    lkg = pkg["selected_last_known_good"]
    for f in ["lkg_receipt_id","lkg_receipt_hash","lkg_artifact_hash","lkg_session_count","lkg_generated_at","lkg_selection_basis","lkg_selection_verdict"]:
        assert f in lkg and lkg[f] not in [None,"","unknown"]

def test_r1_package_contains_selected_last_known_good_snapshot_block():
    pkg = make_valid_r1()
    assert "selected_last_known_good_snapshot" in pkg
    snap = pkg["selected_last_known_good_snapshot"]
    for f in ["canonical_state_payload","canonical_state_hash","artifact_hash","session_count","generated_at"]:
        assert f in snap and snap[f] not in [None,"","unknown"]
    assert isinstance(snap["canonical_state_payload"], dict) and snap["canonical_state_payload"]

def test_r1_package_fails_on_missing_snapshot_session_count():
    bad = {**VALID_SELECTOR}; del bad["lkg_session_count"]
    with pytest.raises((ValueError, KeyError)):
        build_recovery_package_r1("REC-002",VALID_TRIGGER,bad,VALID_SNAPSHOT,52,VALID_AUDIT)

def test_r1_package_fails_on_unknown_session_count():
    bad = {**VALID_SELECTOR,"lkg_session_count":"unknown"}
    with pytest.raises((ValueError, TypeError)):
        build_recovery_package_r1("REC-003",VALID_TRIGGER,bad,VALID_SNAPSHOT,52,VALID_AUDIT)

def test_r1_reject_empty_payload():
    with pytest.raises(ValueError, match="lkg_snapshot_payload must be non-empty dict"):
        build_recovery_package_r1("ID",VALID_TRIGGER,VALID_SELECTOR,{},52,VALID_AUDIT)

def test_r1_reject_missing_selection_audit_field():
    with pytest.raises(ValueError, match="R1_BUILD_FAIL"):
        build_recovery_package_r1("ID",VALID_TRIGGER,VALID_SELECTOR,VALID_SNAPSHOT,52,{"candidate_pool_summary":"P"})

def test_r1_extra_block_rejection():
    pkg = make_valid_r1(); pkg["malicious_extra"] = {"evil":True}
    with pytest.raises(ValueError, match="Whitelist violation"):
        validate_r1_package_integrity(pkg)

def test_r1_snapshot_hash_drift_detection():
    pkg = make_valid_r1()
    pkg["selected_last_known_good_snapshot"]["canonical_state_payload"]["injected"] = "tampered"
    with pytest.raises(ValueError, match="Snapshot Payload/Hash drift"):
        validate_r1_package_integrity(pkg)

def test_r1_package_hash_consistency():
    pkg = make_valid_r1()
    validate_r1_package_integrity(pkg)
