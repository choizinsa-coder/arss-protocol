# Hash Algorithm Agility Specification

**ARSS RPU Specification v0.1 — Supplementary Document**

---

## 1. Purpose

ARSS v0.1 uses SHA-256 as its sole hash algorithm. SHA-256 is considered cryptographically secure today, but no hash algorithm is permanent. Quantum computing advances, cryptanalytic breakthroughs, or regulatory mandates may require transition to a stronger algorithm in the future.

This document defines ARSS's strategy for hash algorithm transition: how the protocol identifies which algorithm is in use, how a transition is executed, and how chains remain verifiable across algorithm boundaries.

---

## 2. Current State (v0.1)

### 2.1 Default Algorithm

| Property | Value |
|---|---|
| Algorithm | SHA-256 |
| Output | 256-bit (64 hex characters, lowercase) |
| Identifier | `sha256` |
| Standard | FIPS 180-4 / RFC 6234 |

### 2.2 Where SHA-256 Is Used

| Computation | Formula |
|---|---|
| `payload_hash` | `SHA256(JCS(payload))` |
| `chain_hash` | `SHA256(prev_hash_bytes \|\| 0x00 \|\| payload_hash_bytes)` |
| `genesis_hash` | `SHA256(JCS(genesis_input))` |
| HACS signature target | `SHA256(JCS({approver_id, approved_rpu_ids, ...}))` |

### 2.3 Implicit Algorithm (v0.1 Behavior)

In v0.1, the hash algorithm is implicit. There is no `hash_algorithm` field in RPU records. All hashes are SHA-256.

This is intentional for v0.1 simplicity. Algorithm identification is deferred to the transition mechanism defined below.

---

## 3. Algorithm Identification

### 3.1 Hash Algorithm Identifier

When algorithm agility is activated (v1.1 or later), hash values SHOULD use a prefixed format for unambiguous identification:

```
<algorithm-id>:<hex-digest>
```

| Algorithm | Identifier | Example Prefix |
|---|---|---|
| SHA-256 | `sha256` | `sha256:3bac33be...` |
| SHA-384 | `sha384` | `sha384:a1b2c3d4...` |
| SHA-512 | `sha512` | `sha512:e5f6a7b8...` |
| SHA3-256 | `sha3-256` | `sha3-256:1a2b3c4d...` |
| SHA3-512 | `sha3-512` | `sha3-512:9e8f7a6b...` |

### 3.2 Backward Compatibility for v0.1

For RPUs with `version: "rpu/1.0"`, the hash algorithm is always SHA-256. No prefix is present. Verifiers MUST treat unprefixed 64-character hex strings as SHA-256 when processing `rpu/1.0` records.

### 3.3 Detection Rule

```
if hash_value contains ":"
    algorithm = prefix before ":"
    digest    = value after ":"
else if hash_value is 64 hex characters
    algorithm = "sha256"  (v0.1 implicit default)
else
    ERROR: unrecognized hash format
```

---

## 4. Transition Procedure

### 4.1 Transition Triggers

Algorithm transition is warranted when:

- A credible cryptanalytic attack reduces SHA-256 security below 128-bit equivalent
- Regulatory bodies (NIST, KISA, BSI) issue deprecation guidance for SHA-256
- Industry standards (ISO 27001, SOC 2) mandate a specific successor algorithm
- A quantum-resistant hash becomes necessary (post-quantum migration)

### 4.2 Transition Phases

| Phase | Name | Actions |
|---|---|---|
| 0 | **Monitoring** | Track NIST/KISA advisories. No action required. Current state |
| 1 | **Dual-Hash Preparation** | Add optional `hash_algorithm` field to RPU spec. Verifier supports multiple algorithms. No chain changes yet |
| 2 | **Dual-Hash Operation** | New RPUs include both old and new algorithm hashes in a dual-hash structure. Chain integrity maintained under both algorithms simultaneously |
| 3 | **New Algorithm Primary** | New RPUs use new algorithm as primary. Old algorithm hash included as optional fallback |
| 4 | **Legacy Sunset** | Old algorithm no longer generated in new RPUs. Old chains remain verifiable under their original algorithm indefinitely |

### 4.3 Dual-Hash Structure (Phase 2–3)

During transition, RPUs carry hashes under both algorithms:

```json
{
  "payload_hash": "sha3-256:1a2b3c4d...",
  "payload_hash_legacy": "sha256:b740309049e5...",
  "chain_hash": "sha3-256:5e6f7a8b...",
  "chain_hash_legacy": "sha256:ea1505232ee2..."
}
```

**Critical rule:** The `chain_hash` computation uses the **primary** algorithm's `prev_hash`. The legacy hash is computed independently for backward verification but does not participate in forward chain linkage.

```
chain_hash        = NEW_ALGO( prev_chain_hash_bytes || 0x00 || payload_hash_bytes )
chain_hash_legacy = SHA256( prev_chain_hash_legacy_bytes || 0x00 || payload_hash_legacy_bytes )
```

### 4.4 Cross-Algorithm Chain Boundary

When a chain transitions from SHA-256 to a new algorithm at RPU-N:

```
RPU-(N-1):  chain_hash = sha256:abc123...
RPU-N:      prev_hash  = sha256:abc123...   (references old algorithm output)
            chain_hash = sha3-256:def456...  (computed under new algorithm)
            chain_hash_legacy = sha256:789abc...
```

RPU-N is the **algorithm transition point**. The `prev_hash` bridges the two algorithms. From RPU-N+1 onward, `prev_hash` references the new algorithm's `chain_hash`.

---

## 5. Verifier Requirements

### 5.1 Algorithm Support Matrix

| Verifier Version | SHA-256 | SHA3-256 | SHA-512 |
|---|---|---|---|
| v0.1 | ✅ Only | ❌ | ❌ |
| v1.1+ (post-agility) | ✅ | ✅ | ✅ |

### 5.2 Verification Rules

1. **Read** the hash value and determine the algorithm (prefix or implicit default)
2. **Verify** the algorithm is supported by the verifier
3. **Compute** using the identified algorithm
4. **Compare** computed vs. declared hash
5. **If dual-hash:** verify both primary and legacy independently; report any mismatch

### 5.3 Unknown Algorithm Handling

If a verifier encounters an unrecognized algorithm identifier, it MUST:

- Report the unknown algorithm clearly
- NOT silently skip the record
- NOT treat the record as valid

---

## 6. Genesis Anchor and Algorithm Agility

### 6.1 Genesis Algorithm Binding

A Genesis Anchor is computed using the algorithm active at chain creation time. The genesis algorithm is permanent for that chain — it is never retroactively re-hashed.

### 6.2 Post-Transition Genesis

For chains created after an algorithm transition, the Genesis Anchor uses the new primary algorithm:

```json
{
  "chain_id": "...",
  "genesis_hash": "sha3-256:...",
  "input": {
    "chain_id": "...",
    "protocol": "ARSS",
    "version": "2.0",
    "timestamp": "..."
  }
}
```

---

## 7. HACS Signature Implications

HACS (Human Actor Cryptographic Signature) uses a hash as the signature target. Algorithm agility applies to this hash as well:

| Phase | HACS Hash |
|---|---|
| v0.1 (current) | `SHA256(JCS({approver_id, approved_rpu_ids, ...}))` |
| Post-transition | `NEW_ALGO(JCS({approver_id, approved_rpu_ids, ...}))` |

The HACS signature algorithm (Ed25519, ECDSA P-256) is independent of the hash algorithm and has its own agility lifecycle. Signature algorithm agility is out of scope for this document.

---

## 8. Implementation Guidance for v0.1

No action is required for v0.1 implementations beyond awareness of this specification. Concrete guidance:

1. **Use SHA-256 exclusively.** No other algorithm is valid for `rpu/1.0`.
2. **Store hashes as lowercase hex strings.** This is forward-compatible with the prefix format.
3. **Do not hard-code SHA-256 in a way that prevents future replacement.** Use an abstraction layer (e.g., `compute_hash(algorithm, data)`) in implementations where practical.
4. **The Reference Verifier** may introduce algorithm abstraction in a future release but is not required to do so for v0.1.

---

## 9. Candidate Algorithms (Informational)

This section is informational and does not prescribe a specific successor algorithm.

| Algorithm | Output Size | Status | Notes |
|---|---|---|---|
| SHA-256 | 256-bit | Current default | FIPS 180-4. Widely deployed |
| SHA-384 | 384-bit | Available | Same family. Larger output |
| SHA-512 | 512-bit | Available | Same family. Largest output |
| SHA3-256 | 256-bit | NIST standardized | Different internal structure (Keccak). Quantum-resilient |
| SHA3-512 | 512-bit | NIST standardized | Larger SHA-3 variant |
| BLAKE3 | 256-bit | Emerging | Very fast. Not yet FIPS standardized |

Algorithm selection will be driven by NIST/KISA guidance, audit ecosystem acceptance, and cross-jurisdictional regulatory alignment.

---

*ARSS Hash Algorithm Agility Specification — AIBA Global Project*
