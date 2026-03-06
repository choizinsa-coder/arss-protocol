# ARSS RPU Specification v0.1

> **Governance is not declared. It is recomputed.**

| Item | Value |
|---|---|
| **Specification** | ARSS Event Model & RPU Specification |
| **Version** | 0.1 — DRAFT |
| **Author** | AIBA Global Project |
| **Domain** | Law & Compliance (initial entry domain) |
| **Verification Hash** | `3BAC33BE74B76B2AED83BE6C3594C7F08D3C9E889ABB9F0B97FD39BFD9E52C14` |

---

## 0. Scope

This specification defines one thing:

> The structure (RPU) for recording governance events so that any AI decision process can be recomputed and verified after the fact by anyone.

**In scope:** Record structure, hash chain rules, event definitions, verification process.

**Out of scope:** Quality or correctness of AI decisions, governance policy content, certification or audit execution, post-v0.1 features (TSA integration, anchoring, Merkle trees).

---

## 1. Design Principles

### 1.1 Recomputable Governance

| Layer | Component |
|---|---|
| Protocol | ARSS (Accountability Record & Structural Signature) |
| Record Unit | RPU (Record Proof Unit) |
| Core Concept | Recomputable Governance |
| Positioning | Governance Verification Infrastructure |

### 1.2 Event Immutability Boundary

- A written RPU payload is never modified.
- Corrections are appended as new events to the chain.
- The `prev_hash` linkage is permanent.
- Deletion does not exist. Cancellation is a new event.

### 1.3 Conflict of Interest Prevention

AIBA is the protocol designer and infrastructure provider. Audit and certification are performed exclusively by independent third parties. This specification guarantees an interface for third-party independent recomputation.

### 1.4 Natural Lock-in

The `prev_hash` chain structure creates a natural switching cost: replacing the governance tool breaks chain continuity. This is a structural property of the protocol, not an artificial barrier.

---

## 2. RPU (Record Proof Unit) Structure

### 2.1 Required Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `rpu_id` | String | Yes | UUIDv7 — time-sortable unique identifier |
| `version` | String | Yes | RPU schema version. See [Schema Versioning](./schema-versioning.md) |
| `timestamp` | String | Yes | ISO 8601 / RFC 3339 UTC, microsecond precision. Example: `2026-03-04T09:00:00.000000Z` |
| `event_type` | String | Yes | Event type identifier. See Section 3 |
| `actor` | Object | Yes | Actor Identity Layer. See Section 2.3 |
| `payload_hash` | String | Yes | `SHA256(JCS(payload))`. Lowercase hex, 64 characters |
| `prev_hash` | String | Yes | `chain_hash` of the immediately preceding RPU. First event uses the Genesis Anchor hash. See [Genesis Anchor](./genesis-anchor.md) |
| `chain_hash` | String | Yes | `SHA256(prev_hash_bytes \|\| 0x00 \|\| payload_hash_bytes)`. See Section 2.2 |
| `governance_context` | Object | Yes | Contains `policy_id`, `authority_root`, `jurisdiction` |
| `payload` | Object | Yes | Event-specific data. See Section 3 |

### 2.2 Canonical Serialization & Hash Computation

**Serialization standard:** JSON Canonicalization Scheme (JCS) per RFC 8785.

| Rule | Detail |
|---|---|
| Field ordering | Unicode code point ascending (including nested objects) |
| Numbers | Integers only. No floating point |
| String encoding | UTF-8. Escape sequences follow JCS rules |
| Null handling | Null-valued fields are excluded (key omitted entirely) |
| Whitespace | None in serialized output |

**Hash formulas:**

```
payload_hash = SHA256( JCS( payload ) )
chain_hash   = SHA256( prev_hash_bytes || 0x00 || payload_hash_bytes )
```

`prev_hash` and `payload_hash` are hex-decoded to raw bytes before concatenation. The separator `0x00` is a single byte.

For hash algorithm extensibility, see [Hash Algorithm Agility](./hash-algorithm-agility.md).

### 2.3 Actor Identity Layer

| Field | Type | Required | Description |
|---|---|---|---|
| `actor.system_actor` | String | Conditional | AI system identifier. Required for AI events |
| `actor.organizational_actor` | String | Conditional | Organization system identifier. Required for org events |
| `actor.human_actor` | String | Conditional | Human identifier (public-key-based deterministic ID). Required for human events |
| `actor.execution_context` | Object | Recommended | Environment metadata: `session_id`, `org_system_version`, `client_ip_hash`, etc. |

---

## 3. Event Model v0.1 — Law & Compliance Domain

| Event | Purpose | Legal Significance |
|---|---|---|
| `AI_OUTPUT_GENERATED` | Record AI agent's autonomous judgment/draft | Immutable evidence of AI involvement and output |
| `HUMAN_REVIEW_LOGGED` | Evidence of expert review process and modifications | Structural proof of professional review obligation |
| `HUMAN_APPROVAL_RECORDED` | Fix legal responsibility (Final Defense) | Cryptographic binding of final decision-maker and approval scope |

### 3.1 AI_OUTPUT_GENERATED

| Payload Field | Type | Required | Description |
|---|---|---|---|
| `event_type` | String | Yes | `"AI_OUTPUT_GENERATED"` |
| `model_id` | String | Yes | AI model identifier. Example: `"claude-sonnet-4-6"` |
| `prompt_hash` | String | Yes | `SHA256(JCS(prompt_payload))` |
| `output_payload_hash` | String | Yes | `SHA256(JCS(output_content))` |
| `confidence_level` | String | No | System-specific confidence indicator |
| `flags` | Array | No | Risk flags detected by the AI system |

Chain rule: `actor.system_actor` must contain an AI system identifier. `actor.human_actor` may be empty.

### 3.2 HUMAN_REVIEW_LOGGED

| Payload Field | Type | Required | Description |
|---|---|---|---|
| `event_type` | String | Yes | `"HUMAN_REVIEW_LOGGED"` |
| `reviewer_id` | String | Yes | Reviewer's public-key-based deterministic identifier |
| `reviewed_rpu_id` | String | Yes | `rpu_id` of the reviewed `AI_OUTPUT_GENERATED` event |
| `review_outcome` | String | Yes | `APPROVED` / `MODIFIED` / `REJECTED` |
| `review_comment_hash` | String | Conditional | `SHA256(JCS(review_comment))`. Required if `MODIFIED` or `REJECTED` |
| `modification_hash` | String | Conditional | SHA256 hash of modified content. Required if `MODIFIED` |
| `review_duration_sec` | Integer | No | Review duration in seconds |

The review comment text is not stored in the RPU. Only its hash is chained; the original is stored separately. This preserves both confidentiality and integrity.

### 3.3 HUMAN_APPROVAL_RECORDED

| Payload Field | Type | Required | Description |
|---|---|---|---|
| `event_type` | String | Yes | `"HUMAN_APPROVAL_RECORDED"` |
| `approver_id` | String | Yes | Approver's public-key-based deterministic identifier |
| `approved_rpu_ids` | Array | Yes | List of approved RPU IDs (both AI_OUTPUT and HUMAN_REVIEW recommended) |
| `final_status` | String | Yes | `APPROVED` / `CONDITIONALLY_APPROVED` / `REJECTED` |
| `approval_scope` | String | Yes | Scope description. Example: `"법률 초안 v2.3 최종 제출 승인"` |
| `hacs_signature` | String | Yes | Approver's cryptographic signature (Ed25519 or ECDSA P-256) |
| `conditions` | Array | Conditional | Condition list. Required if `CONDITIONALLY_APPROVED` |

**HACS signature target:**

```
SHA256(JCS({ approver_id, approved_rpu_ids, final_status, approval_scope, timestamp }))
```

### 3.4 Chain Flow

```
AI_OUTPUT_GENERATED  →  HUMAN_REVIEW_LOGGED  →  HUMAN_APPROVAL_RECORDED
   AI generates          Expert reviews           Final approval
   legal draft           and modifies             + HACS signature
```

This chain functions as a **Decision Reconstruction System**. Anyone who recomputes this chain can reconstruct the actual decision process.

---

## 4. Verification

### 4.1 Three-Step Verification Process

| Step | Name | Operation |
|---|---|---|
| 1 | Single RPU Integrity | JCS-normalize payload → recompute `payload_hash` → compare with declared value |
| 2 | Chain Continuity | Recompute `chain_hash` using `prev_hash` → verify linkage across entire chain |
| 3 | HACS Signature | Verify `HUMAN_APPROVAL_RECORDED` `hacs_signature` using `approver_id` public key |

### 4.2 Reference Verifier

The Reference Verifier is the spec-driven official reference implementation.

- **Phase 1:** CLI (`reference-verifier/src/verifier.py`)
- **Phase 1 (late):** Web Verifier
- **Phase 2:** API

Features: Canonical serialization verification, payload hash recomputation, chain integrity check, RPU schema validation, chain continuity check.

### 4.3 Independent Reproduction

GitHub release includes: sample RPU chain data, Reference Verifier CLI, and a quick verification script. Target: an external developer can independently recompute an RPU chain within 5 minutes of reading the README.

---

## 5. Related Specifications

| Document | Description |
|---|---|
| [Genesis Anchor](./genesis-anchor.md) | Chain origin rules, genesis hash computation, `prev_hash` initialization |
| [Schema Versioning](./schema-versioning.md) | RPU version management, backward compatibility, migration rules |
| [Hash Algorithm Agility](./hash-algorithm-agility.md) | Post-SHA256 algorithm transition path, migration procedures |

---

*ARSS RPU Specification v0.1 — AIBA Global Project*
