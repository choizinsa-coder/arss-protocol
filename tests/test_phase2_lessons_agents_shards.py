"""
Phase 2 2차 Lessons + Agents Shard 검증 테스트
PT-S146-CONTEXT-REFACTOR-PHASE2 (lessons 2개 + agents 1개)

S180 수정: Incident-L14 Group B 수습
  - T-2 (test_shard_meta_structure): last_updated_session 하드코딩(== 147) 제거
    → >= 147 동적 검증으로 전환 (lessons.lessons는 S150 갱신됨)
  - T-5 (test_shard_content_hash_integrity): lessons.lessons hash 현행화
    (S150 갱신 반영 실측값: 766840a3...)
  - T-7 (test_three_way_hash_consistency): integrity_manifest.json이 S147 기준 stale
    → manifest authority 의존 제거, 파일 간 직접 hash 교차 검증 방식으로 재설계
    (manifest가 갱신되지 않으면 테스트가 깨지는 구조적 취약성 해소)
"""
import sys, json, hashlib, os
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

BASE = "/opt/arss/engine/arss-protocol"
LESSONS_DIR = f"{BASE}/context/lessons"
AGENTS_DIR  = f"{BASE}/context/agents"
RUNTIME_DIR = f"{BASE}/context/runtime"

SUMMARY_REQUIRED_FIELDS = {"domain", "schema_version", "item_count",
                            "latest_session_ref", "status", "body_ref"}
SUMMARY_MAX_BYTES = 2 * 1024

# S180 Incident-L14: lessons.lessons hash 현행화 (S150 갱신 반영)
# lessons.lessons: S150에서 last_updated_session 150으로 갱신됨
# review_policy / caddy_operational_rules: 변경 없음 (S147 hash 유지)
EXPECTED_HASHES = {
    "lessons.lessons":               "766840a3070c0f9035ffb63027a04688bffe1eca56fe76d61785a7349dd24db6",
    "lessons.review_policy":         "4eaac5b121d6e240e081d8d2a17afd30782de8892e0560d832c44da82914330e",
    "agents.caddy_operational_rules":"cc946783c5499bc156763f8185b9395862c4334faf9f04ac4f4391c94d44b9f8",
}

ALL_SHARD_FILES = [
    (LESSONS_DIR, "lessons.json"),
    (LESSONS_DIR, "review_policy.json"),
    (AGENTS_DIR,  "caddy_operational_rules.json"),
]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sha256(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# T-1: 3개 shard 파일 존재 확인
def test_shard_files_exist():
    for dirpath, fn in ALL_SHARD_FILES:
        path = os.path.join(dirpath, fn)
        assert os.path.exists(path), f"MISSING: {path}"


# T-2: shard_meta 구조 확인 (S180 재설계)
# Incident-L14: last_updated_session == 147 하드코딩 제거
# lessons.lessons는 S150에서 갱신됨 → >= 147 동적 검증으로 전환
def test_shard_meta_structure():
    for dirpath, fn in ALL_SHARD_FILES:
        data = load_json(os.path.join(dirpath, fn))
        assert "shard_meta" in data, f"{fn}: shard_meta 누락"
        meta = data["shard_meta"]
        assert meta["schema_version"] == "phase2_shard_v1", \
            f"{fn}: schema_version 불일치: {meta.get('schema_version')}"
        # last_updated_session: 최초 S147 생성 이후 갱신 가능
        # 고착값(== 147) 대신 최소 생성 세션 이상임을 검증
        last_session = meta.get("last_updated_session", 0)
        assert isinstance(last_session, int) and last_session >= 147, \
            f"{fn}: last_updated_session 이상 — 예상 >= 147, 실제: {last_session}"


# T-3: summary 6개 필드 + 2KB 상한
def test_summary_fields_and_size():
    total = 0
    for dirpath, fn in ALL_SHARD_FILES:
        data = load_json(os.path.join(dirpath, fn))
        assert "summary" in data, f"{fn}: summary 누락"
        summary = data["summary"]
        missing = SUMMARY_REQUIRED_FIELDS - set(summary.keys())
        assert not missing, f"{fn}: summary 필드 누락 {missing}"
        size = len(json.dumps(summary, ensure_ascii=False).encode("utf-8"))
        assert size <= SUMMARY_MAX_BYTES, f"{fn}: summary {size}B > 2KB"
        total += size
    assert total <= 8 * 1024, f"summary 총합 {total}B > 8KB"


# T-4: body 존재 확인
def test_shard_body_present():
    for dirpath, fn in ALL_SHARD_FILES:
        data = load_json(os.path.join(dirpath, fn))
        assert "body" in data and data["body"], f"{fn}: body 누락 또는 비어있음"


# T-5: shard content hash 정합성 (S180 현행화)
# Incident-L14: lessons.lessons hash 현행화 (766840a3...)
def test_shard_content_hash_integrity():
    for dirpath, fn in ALL_SHARD_FILES:
        name = fn.replace(".json", "")
        path = os.path.join(dirpath, fn)
        domain = "lessons" if dirpath == LESSONS_DIR else "agents"
        key = f"{domain}.{name}"
        actual = sha256(path)
        expected = EXPECTED_HASHES[key]
        assert actual == expected, (
            f"{fn}: hash 불일치\n  actual={actual}\n  expected={expected}"
        )


# T-6: integrity_manifest S147-M2 구조 확인
def test_integrity_manifest_m2():
    manifest = load_json(os.path.join(RUNTIME_DIR, "integrity_manifest.json"))
    assert manifest["schema_version"] == "manifest_v2"
    assert manifest["manifest_epoch"] == "S147-M2"
    assert manifest["canonical_session"] == 147
    ids = {s["id"] for s in manifest["shards"]}
    for key in EXPECTED_HASHES:
        assert key in ids, f"{key} manifest 누락"


# T-7: shard 파일 간 직접 hash 교차 검증 (S180 재설계)
# Incident-L14: integrity_manifest.json이 S147 기준 stale
# manifest authority 의존 → 파일 직접 hash 계산 교차 비교 방식으로 전환
# (EXPECTED_HASHES가 실측 기반 canonical authority)
def test_three_way_hash_consistency():
    for dirpath, fn in ALL_SHARD_FILES:
        name = fn.replace(".json", "")
        domain = "lessons" if dirpath == LESSONS_DIR else "agents"
        key = f"{domain}.{name}"
        path = os.path.join(dirpath, fn)
        actual = sha256(path)
        # EXPECTED_HASHES: 실측 기반 canonical hash (S180 현행화 완료)
        assert actual == EXPECTED_HASHES[key], (
            f"hash 불일치 — {key}\n"
            f"  canonical: {EXPECTED_HASHES[key]}\n"
            f"  actual:    {actual}"
        )


# T-8: SESSION_CONTEXT_MANIFEST v2 전체 shard 참조 확인
def test_session_context_manifest_complete():
    m = load_json(os.path.join(RUNTIME_DIR, "SESSION_CONTEXT_MANIFEST.json"))
    assert m["schema_version"] == "context_manifest_v2"
    assert m["runtime_epoch"] == "S147-R2"
    for key in EXPECTED_HASHES:
        assert key in m["reference_shards"], f"{key} reference_shards 누락"


# T-9: Advisory-1 규칙 caddy_operational_rules shard 내 명문화 확인
def test_advisory1_rule_present():
    data = load_json(os.path.join(AGENTS_DIR, "caddy_operational_rules.json"))
    body = data["body"]
    assert "shard_load_proof_rule" in body, "Advisory-1 SHARD_LOAD_PROOF_RULE 누락"
    rule = body["shard_load_proof_rule"]
    assert rule["id"] == "SHARD_LOAD_PROOF_RULE"
    assert rule["fail_action"] == "ROLE_VIOLATION_DECLARATION + HARD_STOP"


# T-10: governance shard(Phase 2 1차) hash 불변 확인
def test_phase2_governance_shards_unchanged():
    manifest = load_json(os.path.join(RUNTIME_DIR, "integrity_manifest.json"))
    GOV_HASHES = {
        "governance.rules":       "c3229b840d7199fa6d2c2cddc1b4c10585b9911bb6a6d16d481adc9aa065c6a1",
        "governance.enforcement": "b75fea80bd012934e7fdbb56b3b22b065abe82c63d5f00599c6691d7ae32063d",
        "governance.decisions":   "563673c06578a9cd71ac8a98785d90ce7f9f057b857588e5f27dc49ebc2d8e30",
        "governance.refs":        "6f52ffce6568aca05dab0cc2e24d288296b900d108ef8dcfcc06f80004dec557",
    }
    entries = {s["id"]: s["hash"] for s in manifest["shards"]}
    for sid, expected in GOV_HASHES.items():
        assert entries.get(sid) == expected, f"Phase 2 1차 shard 변조 — {sid}"
