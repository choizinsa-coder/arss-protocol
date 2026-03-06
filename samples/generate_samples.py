import json, hashlib

def jcs_serialize(obj):
    if isinstance(obj, dict):
        sorted_items = sorted(obj.items(), key=lambda x: x[0])
        inner = ",".join(f"{jcs_serialize(k)}:{jcs_serialize(v)}" for k, v in sorted_items)
        return "{" + inner + "}"
    elif isinstance(obj, list):
        return "[" + ",".join(jcs_serialize(i) for i in obj) + "]"
    elif isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif obj is None:
        return "null"
    elif isinstance(obj, int):
        return str(obj)
    else:
        raise ValueError(f"Unsupported type: {type(obj)}")

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def compute_payload_hash(payload):
    return sha256_hex(jcs_serialize(payload).encode("utf-8"))

def compute_chain_hash(prev_hash, payload_hash):
    return sha256_hex(bytes.fromhex(prev_hash) + b'\x00' + bytes.fromhex(payload_hash))

genesis_hash = "08b671180438e600b2fbd1ec7942560dccfbdb30c24e1657e8475e3c3c877774"

# RPU #1
rpu1_id = "01956a20-0000-7000-8000-000000000001"
rpu1_payload = {
    "confidence_level": "0.92",
    "event_type": "AI_OUTPUT_GENERATED",
    "flags": [],
    "model_id": "claude-sonnet-4-6",
    "output_payload_hash": sha256_hex(b"draft contract v1 content"),
    "prompt_hash": sha256_hex(b"draft NDA contract for company A")
}
rpu1_ph = compute_payload_hash(rpu1_payload)
rpu1_ch = compute_chain_hash(genesis_hash, rpu1_ph)

rpu1 = {
    "actor": {
        "execution_context": {"session_id": "sess-001"},
        "organizational_actor": "org-lawfirm-001",
        "system_actor": "claude-sonnet-4-6"
    },
    "chain_hash": rpu1_ch,
    "event_type": "AI_OUTPUT_GENERATED",
    "governance_context": {
        "authority_root": "aiba-root-v1",
        "jurisdiction": "KR",
        "policy_id": "legal-compliance-v1"
    },
    "payload": rpu1_payload,
    "payload_hash": rpu1_ph,
    "prev_hash": genesis_hash,
    "rpu_id": rpu1_id,
    "timestamp": "2026-03-06T09:00:00.000000Z",
    "version": "rpu/1.0"
}
with open("/home/claude/arss-protocol/samples/rpu-001-ai-output.json", "w") as f:
    json.dump(rpu1, f, indent=2, ensure_ascii=False)

# RPU #2
rpu2_id = "01956a20-0000-7000-8000-000000000002"
reviewer_id = sha256_hex(b"attorney-kim-public-key")[:16]
rpu2_payload = {
    "event_type": "HUMAN_REVIEW_LOGGED",
    "modification_hash": sha256_hex(b"modified clause 3.1"),
    "prev_hash": rpu1_ch,
    "review_comment_hash": sha256_hex(b"Clause 3.1 needs revision for KR law"),
    "review_duration_sec": 847,
    "review_outcome": "MODIFIED",
    "reviewed_rpu_id": rpu1_id,
    "reviewer_id": reviewer_id
}
rpu2_ph = compute_payload_hash(rpu2_payload)
rpu2_ch = compute_chain_hash(rpu1_ch, rpu2_ph)

rpu2 = {
    "actor": {
        "execution_context": {"session_id": "sess-001"},
        "human_actor": reviewer_id,
        "organizational_actor": "org-lawfirm-001"
    },
    "chain_hash": rpu2_ch,
    "event_type": "HUMAN_REVIEW_LOGGED",
    "governance_context": {
        "authority_root": "aiba-root-v1",
        "jurisdiction": "KR",
        "policy_id": "legal-compliance-v1"
    },
    "payload": rpu2_payload,
    "payload_hash": rpu2_ph,
    "prev_hash": rpu1_ch,
    "rpu_id": rpu2_id,
    "timestamp": "2026-03-06T10:15:00.000000Z",
    "version": "rpu/1.0"
}
with open("/home/claude/arss-protocol/samples/rpu-002-human-review.json", "w") as f:
    json.dump(rpu2, f, indent=2, ensure_ascii=False)

# RPU #3
rpu3_id = "01956a20-0000-7000-8000-000000000003"
approver_id = sha256_hex(b"partner-lee-public-key")[:16]
approval_scope = "NDA contract v1.1 final submission approval"
hacs_input = {
    "approval_scope": approval_scope,
    "approved_rpu_ids": [rpu1_id, rpu2_id],
    "approver_id": approver_id,
    "final_status": "APPROVED",
    "timestamp": "2026-03-06T11:30:00.000000Z"
}
hacs_signature = sha256_hex(jcs_serialize(hacs_input).encode("utf-8"))
rpu3_payload = {
    "approval_scope": approval_scope,
    "approved_rpu_ids": [rpu1_id, rpu2_id],
    "approver_id": approver_id,
    "event_type": "HUMAN_APPROVAL_RECORDED",
    "final_status": "APPROVED",
    "hacs_signature": hacs_signature
}
rpu3_ph = compute_payload_hash(rpu3_payload)
rpu3_ch = compute_chain_hash(rpu2_ch, rpu3_ph)

rpu3 = {
    "actor": {
        "execution_context": {"session_id": "sess-001"},
        "human_actor": approver_id,
        "organizational_actor": "org-lawfirm-001"
    },
    "chain_hash": rpu3_ch,
    "event_type": "HUMAN_APPROVAL_RECORDED",
    "governance_context": {
        "authority_root": "aiba-root-v1",
        "jurisdiction": "KR",
        "policy_id": "legal-compliance-v1"
    },
    "payload": rpu3_payload,
    "payload_hash": rpu3_ph,
    "prev_hash": rpu2_ch,
    "rpu_id": rpu3_id,
    "timestamp": "2026-03-06T11:30:00.000000Z",
    "version": "rpu/1.0"
}
with open("/home/claude/arss-protocol/samples/rpu-003-human-approval.json", "w") as f:
    json.dump(rpu3, f, indent=2, ensure_ascii=False)

print(f"Sample files generated. Final chain_hash: {rpu3_ch}")
