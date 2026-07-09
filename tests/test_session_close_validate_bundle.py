"""
test_session_close_validate_bundle.py
IAPG-III Phase1.5 (S356) - validate_bundle 4수 유니트 테스트
EAG: EAG-S356-IAPG-PHASE15-IMPL-002
"""
import hashlib, json, os, sys, tempfile

sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.close.session_close_generator import validate_bundle


def _mk_final(session=356, extra=None):
    data = {"session_count": session, "chain": {"tip": "abc1234"}}
    if extra:
        data.update(extra)
    payload = {k: v for k, v in data.items() if k != "context_hash"}
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    data["context_hash"] = h
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, f, ensure_ascii=False)
    f.close()
    return f.name, h


TS = "2026-07-09T12:00:00.000000+09:00"

def _ptr(h, **kw):
    d = {"current_session": 356, "context_hash": h, "generated_at": TS}
    d.update(kw)
    return d

def _mft(h, **kw):
    d = {"session_count": 356, "context_hash": h, "updated_at": TS, "status": "FRESH"}
    d.update(kw)
    return d


def test_validate_bundle_pass():
    fp, h = _mk_final()
    ok, errors = validate_bundle(356, h, _ptr(h), _mft(h), fp)
    os.unlink(fp)
    assert ok, errors


def test_validate_bundle_timestamp_desync():
    fp, h = _mk_final()
    ptr = _ptr(h, generated_at="2026-07-09T10:59:10.380411+09:00")
    mft = _mft(h, updated_at="2026-07-09T10:59:10.380781+09:00")
    ok, errors = validate_bundle(356, h, ptr, mft, fp)
    os.unlink(fp)
    assert not ok
    assert any("TIMESTAMP" in e for e in errors)


def test_validate_bundle_session_mismatch():
    fp, h = _mk_final()
    ok, errors = validate_bundle(356, h, _ptr(h, current_session=999), _mft(h), fp)
    os.unlink(fp)
    assert not ok
    assert any("SESSION" in e for e in errors)


def test_validate_bundle_hash_mismatch():
    fp, h = _mk_final()
    ok, errors = validate_bundle(356, h, _ptr("b"*64), _mft(h), fp)
    os.unlink(fp)
    assert not ok
    assert any("HASH" in e for e in errors)


def test_validate_bundle_final_tampered():
    fp, h = _mk_final()
    with open(fp, "w", encoding="utf-8") as f:
        json.dump({"tampered": True, "context_hash": h}, f)
    ok, errors = validate_bundle(356, h, _ptr(h), _mft(h), fp)
    os.unlink(fp)
    assert not ok
    assert any("FINAL_HASH_MISMATCH" in e for e in errors)


def test_validate_bundle_final_missing():
    fp, h = _mk_final()
    os.unlink(fp)
    ok, errors = validate_bundle(356, h, _ptr(h), _mft(h), fp)
    assert not ok
    assert any("FINAL_MISSING" in e for e in errors)
