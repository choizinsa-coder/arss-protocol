# ARSS — Accountability Record & Structural Signature

**ARSS is an open protocol for recording AI governance decisions as a cryptographic chain that anyone can independently recompute and verify.**

---

## The Problem

Current AI governance relies on declarations, not evidence.

Audit reports assert that a governance process occurred.  
Policy documents declare that controls were followed.  
Compliance records state that decisions were reviewed.

None of these produce a record that an independent party can recompute.  
If the record cannot be recomputed, it cannot be verified.  
If it cannot be verified, it is trust — not proof.

ARSS addresses this gap.

---

## How ARSS Works

ARSS converts governance events into **Record Proof Units (RPUs)** — deterministically serialized, cryptographically chained records that preserve the integrity of each decision point.

```
Governance Event
       │
       ▼
JCS Canonicalization          ← RFC 8785, deterministic byte sequence
       │
       ▼
Payload Hash                  ← SHA256(canonical_json(payload))
       │
       ▼
Hash Chain                    ← SHA256(prev_hash + ":" + payload_hash)  [UTF-8]
       │
       ▼
RPU Record                    ← independently recomputable
       │
       ▼
Reference Verifier            ← any third party, any environment
```

**Three core mechanisms:**

1. **Deterministic serialization** — each governance event is normalized using JSON Canonicalization Scheme (JCS / RFC 8785), producing an identical byte sequence regardless of environment. Keys are sorted in ascending alphabetical order, recursively.
2. **Hash chaining** — each RPU embeds the hash of the previous record:
   ```
   chain_hash = SHA256(prev_hash + ":" + payload_hash)  [UTF-8 encoded]
   genesis    = SHA256("GENESIS:" + payload_hash)
   ```
3. **Independent recomputability** — any party with the raw records can recompute the chain and confirm integrity without access to the original system

### RPU Required Fields

| Field | Type | Description |
|---|---|---|
| `rpu_id` | string | Record identifier (`RPU-000X` format · Phase A) |
| `version` | string | Protocol version (`rpu/1.0`) |
| `timestamp` | ISO 8601 UTC | Second precision (e.g. `2026-03-22T05:08:54Z`) |
| `actor_id` | string | Identifier of the decision actor |
| `payload_hash` | SHA256 hex | Hash of the governance event payload |
| `governance_context` | object | Policy ID, Authority Root, Jurisdiction |
| `prev_hash` | SHA256 hex | Hash of the preceding RPU chain_hash |

All meta-fields (`actor_id`, `timestamp`, `event_type`, `governance_context`, `sequence_label`, `version`) are located **inside** the `payload` block. The `chain` block contains only `prev_hash`, `payload_hash`, and `chain_hash`.

---

## Quick Start — Inspect the Protocol

Review the reference generator and verifier source, then inspect the live production chain.

**Requirements:** Python 3.8+

```bash
# 1. Clone the repository
git clone https://github.com/choizinsa-coder/arss-protocol
cd arss-protocol

# 2. Run the reference verifier against the sample chain
python3 reference-verifier/src/verifier.py samples/

# 3. Inspect the reference generator (Canonical Schema v1.0)
cat reference-generator/src/arss_generator_v1.py

# 4. Inspect the production chain
cat reference-verifier/SNAPSHOT_LOG/ledger.json
cat reference-verifier/SNAPSHOT_LOG/rpu-0007.json
cat reference-verifier/SNAPSHOT_LOG/rpu-0008.json
```

> **[PHASE 1 — VERIFIER ACTIVE · PRODUCTION CHAIN OPERATIONAL]**
> The reference verifier is deployed and confirmed operational.
> Generator v1.0 has passed Internal Proof Mode verification:
> Determinism (10/10), JCS normalization (3/3), Chain integrity attacks (3/3), Ledger integrity (3/3).
> All tests PASS. Production chain is live from RPU-0004 through RPU-0008.

To recompute a chain hash manually:

```python
import hashlib, json

def canonical_json(obj):
    if isinstance(obj, dict):
        sorted_items = sorted(obj.items(), key=lambda x: x[0])
        inner = ",".join(f'"{k}":{canonical_json(v)}' for k, v in sorted_items)
        return "{" + inner + "}"
    # ... (see reference-generator/src/arss_generator_v1.py for full implementation)

payload_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
chain_hash   = hashlib.sha256((prev_hash + ":" + payload_hash).encode("utf-8")).hexdigest()
```

---

## Repository Structure

```
arss-protocol/
├── spec/                         # Protocol specification (Markdown)
│   ├── rpu-schema.md             # RPU field definitions and constraints
│   ├── hash-chain.md             # Chain construction and verification rules
│   └── canonicalization.md       # JCS normalization requirements
│
├── reference-verifier/           # Minimal Python verifier
│   └── src/
│       └── verifier.py
│
├── reference-generator/          # Reference RPU generator (Canonical Schema v1.0)
│   └── src/
│       └── arss_generator_v1.py
│
├── SNAPSHOT_LOG/                 # Live production chain records
│   ├── ledger.json               # Full chain index + state registry
│   ├── rpu-0004.json             # GOVERNANCE_EVENT — Production chain genesis
│   ├── rpu-0005.json             # DECISION
│   ├── rpu-0006.json             # APPROVAL  (STATE-001 activation)
│   ├── rpu-0007.json             # EXECUTION (STATE-002 activation)
│   └── rpu-0008.json             # EVIDENCE  (Internal Proof Mode seal)
│
├── samples/                      # Minimal sample chain for quick inspection
│   └── genesis.json
│
└── tests/                        # Verification test vectors
    └── test_vectors.json
```

---

## Verification Logic

The reference verifier performs three sequential checks:

**Step 1 — Single RPU integrity**  
Apply JCS normalization to each RPU payload. Recompute `payload_hash`. Confirm match.

**Step 2 — Chain continuity**  
For each RPU at position `n`, confirm:
```
chain_hash[n] == SHA256(chain_hash[n-1] + ":" + payload_hash[n])  [UTF-8]
```

**Step 3 — HACS verification** *(implemented — public specification: v0.2 planned)*  
Verify HACS (Human Actor Cryptographic Signature) if present in `governance_context`.

A chain that passes all three steps is structurally sound — its integrity can be confirmed by any independent party without access to the originating system.

---

## Protocol Status

ARSS is an open protocol under active development.

Current release: **v0.1 · PHASE 1 — VERIFIER ACTIVE · PRODUCTION CHAIN OPERATIONAL**

> **[PHASE 1 — INTERNAL PROOF MODE: ALL PASS]**
> Generator v1.0 (Canonical Schema v1.0 LOCK) has completed full internal verification:
> - Determinism: 10/10 identical outputs confirmed
> - JCS normalization: key-order / whitespace / compact variants — all produce identical hash
> - Chain integrity: payload tampering, prev_hash forgery, chain_hash forgery — all detected (FAIL as expected)
> - Ledger integrity: duplicate is_current, chain discontinuity, chain_tip mismatch — all detected (FAIL as expected)
>
> Production chain (RPU-0004 ~ RPU-0008) is live. STATE-002 Operational State active.

**Progress:**

- [x] RPU schema defined
- [x] Hash chain formula specified (Canonical Schema v1.0 LOCK)
- [x] JCS normalization requirement documented
- [x] Reference verifier source (Python, single-file)
- [x] Reference generator source (Python · arss_generator_v1.py)
- [x] Sample chain structure
- [x] Internal Proof Mode — ALL PASS (2026-03-22)
- [x] Production chain live — RPU-0004 ~ RPU-0008 (STATE-002 ACTIVE)
- [x] HACS verification logic (implemented — public spec: v0.2 planned)
- [ ] Formal test vector suite
- [ ] Multi-language verifier implementations

**Verification anchor hashes (Canonical Schema v1.0 · 2026-03-22):**

Genesis Anchor (protocol specification baseline):
```
3BAC33BE74B76B2AED83BE6C3594C7F08D3C9E889ABB9F0B97FD39BFD9E52C14
```

Production Chain Tip (STATE-002 · RPU-0008 · independently recomputable):
```
3fa890300b41871f9e3aa0ed0d6b8463231bb75efba9dd250bccdf3e3e572c52
```

The Chain Tip is independently recomputable from the raw RPU records in `SNAPSHOT_LOG/`
using the reference generator or any SHA256 implementation.
Recomputation requires no access to AIBA infrastructure.

---

## Roadmap

| Version | Scope | Status |
|---------|-------|--------|
| v0.1 | Hash-chain governance evidence protocol · PHASE 1 — VERIFIER ACTIVE | **Current** |
| v0.2 | HACS: Hash-Anchored Cryptographic Signatures — public specification, key management guidelines, trust anchor architecture | Planned |

---

**Recomputable, not trusted.**  
Any claim about a governance chain's integrity must be independently verifiable from the raw records alone.

**Deterministic, not environment-dependent.**  
JCS normalization guarantees that the same governance event produces the same byte sequence on any machine.

**Open, not proprietary.**  
The protocol specification and reference verifier are open. No dependency on AIBA infrastructure is required for verification.

---

## Design Rationale

For technical positioning and design decisions — including comparisons with blockchain and transparency logs, and the limits of cryptographic integrity — see [DESIGN.md](DESIGN.md).

---

## Contributing

ARSS is an open protocol. Contributions welcome:

- Protocol critique and edge case analysis
- Additional language implementations of the reference verifier
- Test vector submissions
- Integration proposals

Open an issue or submit a pull request.

---

## License

- **Protocol specification** (`spec/`): [Apache 2.0](LICENSE-SPEC)
- **Reference verifier** (`reference-verifier/`): [MIT](LICENSE-VERIFIER)

ARSS protocol development is initiated by **AIBA Global**.  
The protocol specification is independent of AIBA's commercial infrastructure.

---

*"Governance is not declared. It is recomputed."*
