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
Payload Hash (SHA256)
       │
       ▼
Hash Chain  ←  SHA256(prev_hash ‖ 0x00 ‖ payload_c14n)
       │
       ▼
RPU Record                    ← independently recomputable
       │
       ▼
Reference Verifier            ← any third party, any environment
```

**Three core mechanisms:**

1. **Deterministic serialization** — each governance event is normalized using JSON Canonicalization Scheme (JCS / RFC 8785), producing an identical byte sequence regardless of environment
2. **Hash chaining** — each RPU embeds the hash of the previous record:
   ```
   SHA256(prev_hash || 0x00 || payload_c14n)
   ```
3. **Independent recomputability** — any party with the raw records can recompute the chain and confirm integrity without access to the original system

### RPU Required Fields

| Field | Type | Description |
|---|---|---|
| `rpu_id` | UUIDv7 | Monotonically ordered record identifier |
| `version` | string | Protocol version (`rpu/1.0`) |
| `timestamp` | ISO 8601 UTC | Microsecond precision |
| `actor_id` | string | Deterministic identifier derived from the actor's public key |
| `payload_hash` | SHA256 | Hash of the governance event payload |
| `governance_context` | object | Policy ID, Authority Root, Jurisdiction |
| `prev_hash` | SHA256 | Hash of the preceding RPU (genesis: `0x00…00`) |

---

## Quick Start — Inspect the Protocol

Review the reference verifier source and sample chain structure.

**Requirements:** Python 3.8+

```bash
# 1. Clone the repository
git clone https://github.com/choizinsa-coder/arss-protocol
cd arss-protocol

# 2. Inspect the reference verifier
cat reference-verifier/src/verifier.py

# 3. Inspect the sample chain structure
cat samples/genesis.json
cat samples/rpu-001.json
```

> **Note [PRE-RPU · PHASE 0]:** The reference verifier is not yet deployed for live execution.
> Full verifier execution — including chain continuity and HACS signature checks — will be available in Phase 1 upon infrastructure deployment.
> The sample chain in `samples/` is a specification prototype, not a cryptographically verified chain.

To recompute a single RPU hash manually:

```python
import hashlib, json

# Load normalized payload (JCS)
payload_c14n = b'...'          # canonical JSON bytes
prev_hash    = bytes(32)       # 32 zero-bytes for genesis RPU

digest = hashlib.sha256(prev_hash + b'\x00' + payload_c14n).hexdigest()
print(digest)
```

---

## Repository Structure

```
arss-protocol/
├── spec/                    # Protocol specification (Markdown)
│   ├── rpu-schema.md        # RPU field definitions and constraints
│   ├── hash-chain.md        # Chain construction and verification rules
│   └── canonicalization.md  # JCS normalization requirements
│
├── reference-verifier/      # Minimal Python verifier
│   └── src/
│       └── verifier.py
│
├── samples/                 # Sample governance chain (PRE-RPU spec prototype)
│   ├── genesis.json
│   ├── rpu-001.json
│   ├── rpu-002.json
│   └── rpu-003.json
│
└── tests/                   # Verification test vectors
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
rpu[n].prev_hash == SHA256(rpu[n-1].prev_hash || 0x00 || rpu[n-1].payload_c14n)
```

**Step 3 — HACS verification** *(implemented — public specification: v0.2 planned)*  
Verify HACS (Human Actor Cryptographic Signature) if present in `governance_context`. The reference verifier includes HACS verification logic; the public key specification and key management guidelines are scoped to v0.2.

A chain that passes all three steps is structurally sound — its integrity can be confirmed by any independent party without access to the originating system.

---

## Protocol Status

ARSS is an open protocol under active development.

Current release: **v0.1 (specification draft) · PHASE 0 — PRE-RPU**

> **[PRE-RPU · PHASE 0]** The current state is specification and infrastructure preparation.
> Live verifier execution and cryptographically verified chain generation will begin in Phase 1,
> upon completion of: VPS deployment, reference verifier execution confirmed, and sample RPU hash recomputation verified.

- [x] RPU schema defined
- [x] Hash chain formula specified
- [x] JCS normalization requirement documented
- [x] Reference verifier source (Python, single-file)
- [x] Sample chain structure (spec prototype · PRE-RPU)
- [ ] Reference verifier live deployment (Phase 1)
- [ ] Formal test vector suite
- [ ] Multi-language verifier implementations
- [x] HACS verification logic (implemented — public spec: v0.2 planned)

The v0.1 verification anchor hash is:
```
3BAC33BE74B76B2AED83BE6C3594C7F08D3C9E889ABB9F0B97FD39BFD9E52C14
```

This hash is derived from the protocol specification and will be independently recomputable
from the sample chain once the reference verifier is deployed in Phase 1.

---

## Roadmap

| Version | Scope | Status |
|---------|-------|--------|
| v0.1 | Hash-chain governance evidence protocol · specification draft | Current |
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
