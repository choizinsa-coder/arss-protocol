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

## Quick Start — 5-Minute Verification

Verify a sample governance chain locally.

**Requirements:** Python 3.8+

```bash
# 1. Clone the repository
git clone https://github.com/choizinsa-coder/arss-protocol
cd arss-protocol

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the reference verifier against the sample chain
python reference-verifier/src/verifier.py samples
```

**Expected output:**

```
ARSS Reference Verifier v0.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Chain : genesis → rpu-001 → rpu-002 → rpu-003
JCS normalization: PASS
Hash chain       : PASS
Anchor hash      : 3BAC33BE74B76B2AED83BE6C3594C7F08D3C9E889ABB9F0B97FD39BFD9E52C14

RESULT: ALL PASS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

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
├── samples/                 # Sample governance chain (directory of RPUs)
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

Current release: **v0.1 (specification draft)**

- [x] RPU schema defined
- [x] Hash chain formula specified
- [x] JCS normalization requirement documented
- [x] Reference verifier (Python, single-file)
- [x] Sample chain with known verification hash
- [ ] Formal test vector suite
- [ ] Multi-language verifier implementations
- [x] HACS verification logic (implemented — public spec: v0.2 planned)

The v0.1 verification anchor hash is:
```
3BAC33BE74B76B2AED83BE6C3594C7F08D3C9E889ABB9F0B97FD39BFD9E52C14
```

This hash is publicly declared and independently recomputable from the sample chain in `samples/`.

---

## Roadmap

| Version | Scope | Status |
|---------|-------|--------|
| v0.1 | Hash-chain governance evidence protocol | Current |
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

ARSS protocol development is initiated by **[AIBA Global](https://aiba.global)**.  
The protocol specification is independent of AIBA's commercial infrastructure.

---

*"Governance is not declared. It is recomputed."*
