"""
Phase 2 Governance Shard 검증 테스트
PT-S146-CONTEXT-REFACTOR-PHASE2 (governance 4개 shard)
"""
import sys, json, hashlib, os
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

BASE = "/opt/arss/engine/arss-protocol"
GOV_DIR = f"{BASE}/context/governance"
RUNTIME_DIR = f"{BASE}/context/runtime"

SHARD_FILES = ["rules.json", "enforcement.json", "decisions.json", "refs.json"]
SUMMARY_REQUIRED_FIELDS = {"domain", "schema_version", "item_count",
                            "latest_session_ref", "status", "body_ref"}
SUMMARY_MAX_BYTES = 2 * 1024  # 2KB per shard

EXPECTED_HASHES = {
    "rules":       "563ab1b4573d7c1cac6a3ce4ec4757d557766483867b85cdbf1d569f87767c46",
    "enforcement": "b75fea80bd012934e7fdbb56b3b22b065abe82c63d5f00599c6691d7ae32063d",
    "decisions":   "563673c06578a9cd71ac8a98785d90ce7f9f057b857588e5f27dc49ebc2d8e30",
    "refs":        "6f52ffce6568aca05dab0cc2e24d288296b900d108ef8dcfcc06f80004dec557",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sha256(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# T-1: 4개 shard 파일 존재 확인
def test_governance_shard_files_exist():
    for fn in SHARD_FILES:
        path = os.path.join(GOV_DIR, fn)
        assert os.path.exists(path), f"MISSING: {path}"


# T-2: shard_meta 구조 확인
def test_shard_meta_structure():
    for fn in SHARD_FILES:
        data = load_json(os.path.join(GOV_DIR, fn))
        assert "shard_meta" in data, f"{fn}: shard_meta 누락"
        meta = data["shard_meta"]
        assert meta["schema_version"] == "phase2_shard_v1", f"{fn}: schema_version 불일치"
        assert meta["domain"] == "governance", f"{fn}: domain 불일치"
        assert meta["last_updated_session"] == 147, f"{fn}: session 불일치"


# T-3: summary 6개 필드 존재 + 2KB 상한
def test_summary_fields_and_size():
    total = 0
    for fn in SHARD_FILES:
        data = load_json(os.path.join(GOV_DIR, fn))
        assert "summary" in data, f"{fn}: summary 누락"
        summary = data["summary"]
        missing = SUMMARY_REQUIRED_FIELDS - set(summary.keys())
        assert not missing, f"{fn}: summary 필드 누락 {missing}"
        size = len(json.dumps(summary, ensure_ascii=False).encode("utf-8"))
        assert size <= SUMMARY_MAX_BYTES, f"{fn}: summary {size}B > 2KB 한도"
        total += size
    assert total <= 8 * 1024, f"summary 총합 {total}B > 8KB 한도"


# T-4: body 존재 확인
def test_shard_body_present():
    for fn in SHARD_FILES:
        data = load_json(os.path.join(GOV_DIR, fn))
        assert "body" in data, f"{fn}: body 누락"
        assert data["body"], f"{fn}: body 비어있음"


# T-5: shard content hash 검증 (3자 정합성 중 shard 측)
def test_shard_content_hash_integrity():
    for fn in SHARD_FILES:
        name = fn.replace(".json", "")
        path = os.path.join(GOV_DIR, fn)
        actual = sha256(path)
        expected = EXPECTED_HASHES[name]
        assert actual == expected, (
            f"{fn}: hash 불일치\n  actual={actual}\n  expected={expected}"
        )


# T-6: integrity_manifest v2 구조 확인
def test_integrity_manifest_v2():
    manifest = load_json(os.path.join(RUNTIME_DIR, "integrity_manifest.json"))
    assert manifest["schema_version"] == "manifest_v2", "manifest schema_version != manifest_v2"
    assert manifest["canonical_session"] == 147
    ids = {s["id"] for s in manifest["shards"]}
    for name in ["rules", "enforcement", "decisions", "refs"]:
        assert f"governance.{name}" in ids, f"governance.{name} manifest 누락"


# T-7: manifest hash ↔ shard hash 3자 정합성
def test_three_way_hash_consistency():
    manifest = load_json(os.path.join(RUNTIME_DIR, "integrity_manifest.json"))
    gov_entries = {
        s["id"].replace("governance.", ""): s["hash"]
        for s in manifest["shards"]
        if s["id"].startswith("governance.")
    }
    for name, expected_hash in gov_entries.items():
        actual = sha256(os.path.join(GOV_DIR, f"{name}.json"))
        assert actual == expected_hash, (
            f"3자 hash 불일치 — governance.{name}\n"
            f"  manifest: {expected_hash}\n  actual:   {actual}"
        )


# T-8: SESSION_CONTEXT_MANIFEST v2 확인
def test_session_context_manifest_v2():
    m = load_json(os.path.join(RUNTIME_DIR, "SESSION_CONTEXT_MANIFEST.json"))
    assert m["schema_version"] == "context_manifest_v2"
    assert m["session_count"] == 147
    for name in ["rules", "enforcement", "decisions", "refs"]:
        key = f"governance.{name}"
        assert key in m["reference_shards"], f"{key} reference_shards 누락"


# T-9: summary status 필드가 "active"인지 확인 (판단 오용 방지 간접 검증)
def test_summary_status_active():
    for fn in SHARD_FILES:
        data = load_json(os.path.join(GOV_DIR, fn))
        assert data["summary"]["status"] == "active", f"{fn}: summary.status != active"


# T-10: runtime shard(Phase 1) 불변 확인 — 기존 hash 유지
def test_phase1_runtime_shards_unchanged():
    manifest = load_json(os.path.join(RUNTIME_DIR, "integrity_manifest.json"))
    runtime_entries = {
        s["id"]: s["hash"]
        for s in manifest["shards"]
        if s.get("size_class") == "runtime"
    }
    PHASE1_HASHES = {
        "chain_state":   "8d521692428228b5d07f08d4e275a07b158f63999c334ed2d3eddde91324a913",
        "active_state":  "e80372c58dc6c3d46a080538331f7099bfd0130d0f80724c42804bd8cef3b9d6",
        "session_delta": "33c7d40a0a6a0f062ed1ed1584eada358b36b893cb8563ef478f0dd0f8ab6d2d",
    }
    for shard_id, expected in PHASE1_HASHES.items():
        actual = runtime_entries.get(shard_id)
        assert actual == expected, (
            f"Phase 1 shard 변조 감지 — {shard_id}\n"
            f"  manifest: {actual}\n  expected: {expected}"
        )
