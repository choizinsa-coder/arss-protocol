# Genesis Anchor Specification

**ARSS RPU Specification v0.1 — Supplementary Document**

---

## 1. Purpose

The Genesis Anchor is the cryptographic origin point of every ARSS chain. It establishes the initial `prev_hash` value that the first RPU in a chain references, creating an unforgeable starting point for the entire hash chain.

Without a well-defined genesis, there is no deterministic way to verify the integrity of a chain from its very first record.

---

## 2. Genesis Anchor Structure

A Genesis Anchor is a standalone JSON record with the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `chain_id` | String | Yes | UUIDv4 — unique identifier for this chain instance |
| `genesis_hash` | String | Yes | `SHA256(JCS(input))`. The computed anchor hash |
| `input` | Object | Yes | The canonical input object used to compute `genesis_hash` |
| `note` | String | No | Human-readable description. Not included in hash computation |

### 2.1 Genesis Input Object

The `input` object contains the minimum fields necessary to deterministically produce the genesis hash:

| Field | Type | Required | Description |
|---|---|---|---|
| `chain_id` | String | Yes | Must match the top-level `chain_id` |
| `protocol` | String | Yes | Fixed value: `"ARSS"` |
| `version` | String | Yes | Protocol version at chain creation. Example: `"1.0"` |
| `timestamp` | String | Yes | Chain creation time. ISO 8601 / RFC 3339 UTC, microsecond precision |

### 2.2 Computation Rule

```
genesis_hash = SHA256( JCS( input ) )
```

The `input` object is serialized using JCS (RFC 8785) — keys sorted by Unicode code point, no whitespace — then SHA256-hashed.

### 2.3 Example

```json
{
  "chain_id": "7c926bb0-e053-4c31-a438-a79b5ff89a50",
  "genesis_hash": "08b671180438e600b2fbd1ec7942560dccfbdb30c24e1657e8475e3c3c877774",
  "input": {
    "chain_id": "7c926bb0-e053-4c31-a438-a79b5ff89a50",
    "protocol": "ARSS",
    "timestamp": "2026-03-06T00:00:00.000000Z",
    "version": "1.0"
  },
  "note": "Genesis Anchor: SHA256(JCS(input)). First prev_hash of this chain."
}
```

Verification:

```
JCS(input) = {"chain_id":"7c926bb0-e053-4c31-a438-a79b5ff89a50","protocol":"ARSS","timestamp":"2026-03-06T00:00:00.000000Z","version":"1.0"}

SHA256(above) = 08b671180438e600b2fbd1ec7942560dccfbdb30c24e1657e8475e3c3c877774
```

---

## 3. Chain Linkage Rules

### 3.1 First RPU in a Chain

The first RPU in any ARSS chain MUST set its `prev_hash` field to the `genesis_hash` of the chain's Genesis Anchor.

```
RPU-001.prev_hash == genesis.genesis_hash
```

### 3.2 Subsequent RPUs

Every subsequent RPU sets `prev_hash` to the `chain_hash` of the immediately preceding RPU.

```
RPU-N.prev_hash == RPU-(N-1).chain_hash
```

### 3.3 Chain Hash Computation

This rule applies uniformly to all RPUs, including the first:

```
chain_hash = SHA256( prev_hash_bytes || 0x00 || payload_hash_bytes )
```

The genesis hash participates in this computation exactly as any other `prev_hash` — there is no special case for the first RPU's chain hash formula.

---

## 4. Constraints

### 4.1 One Genesis per Chain

Each `chain_id` has exactly one Genesis Anchor. Creating a second Genesis Anchor for the same `chain_id` is a protocol violation.

### 4.2 Genesis Is Immutable

Once a Genesis Anchor is published, its `input` and `genesis_hash` are permanent. They cannot be revised, replaced, or retroactively modified.

### 4.3 Genesis File Location

In a standard ARSS repository layout, the Genesis Anchor is stored as:

```
samples/genesis.json
```

The Reference Verifier reads this file first and aborts verification if the declared `genesis_hash` does not match `SHA256(JCS(input))`.

### 4.4 chain_id Consistency

The `chain_id` in the Genesis Anchor identifies the chain. All RPUs in the chain belong to this `chain_id`. Implementations SHOULD validate that RPU metadata references the correct `chain_id` where applicable.

---

## 5. Verification Procedure

A verifier MUST perform the following steps before processing any RPU:

1. **Load** `genesis.json`
2. **Compute** `SHA256(JCS(genesis.input))`
3. **Compare** the computed value against `genesis.genesis_hash`
4. **Abort** if mismatch — the chain's origin is unverifiable
5. **Set** `prev_hash = genesis_hash` for processing the first RPU

This procedure is implemented in the Reference Verifier (`reference-verifier/src/verifier.py`, lines 90–107).

---

## 6. Design Rationale

### Why a separate Genesis record?

The Genesis Anchor is not an RPU. It does not have `event_type`, `actor`, `payload`, or other RPU fields. This separation exists because the genesis serves a single purpose — establishing the cryptographic root of trust for a chain — and mixing this with business-level event data would violate the principle of minimal responsibility per record.

### Why not use a zero hash?

Using `prev_hash = "0000...0000"` as the first RPU's predecessor would work mechanically, but it carries no verifiable information. The Genesis Anchor binds chain identity (`chain_id`), protocol version, and creation time into the starting hash, making the chain's origin itself auditable.

### Why include `version` in genesis input?

The protocol version at chain creation time is permanently recorded. If ARSS evolves (e.g., `"2.0"`), a chain's genesis reveals which protocol generation it belongs to, enabling version-aware verification without external metadata.

---

## 7. Future Considerations (Post-v0.1)

- **TSA timestamping** of the Genesis Anchor for external time authority binding
- **Anchoring** the genesis hash to a public ledger for third-party auditability
- **Multi-chain federation** rules for cross-chain genesis references

These are out of scope for v0.1.

---

*ARSS Genesis Anchor Specification — AIBA Global Project*
