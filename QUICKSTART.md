# ARSS Quick Start

Inspect the governance chain protocol and prepare for verification.

> **[PRE-RPU · PHASE 0]** The reference verifier is not yet deployed for live execution.
> This Quick Start guides you through protocol inspection and manual hash recomputation.
> Full automated verification will be available in Phase 1 upon infrastructure deployment.

---

## Prerequisites

- Python 3.8+
- No external dependencies required

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/choizinsa-coder/arss-protocol
cd arss-protocol
```

---

## Step 2 — Inspect the Sample Chain

The `samples/` directory contains a spec prototype chain (PRE-RPU):

```
samples/
├── genesis.json       ← Chain start anchor
├── rpu-001.json       ← First governance record
├── rpu-002.json       ← Second governance record
└── rpu-003.json       ← Third governance record
```

> These files are **specification prototypes**, not cryptographically verified chains.
> They demonstrate the RPU structure and hash chain formula defined in the protocol spec.

Inspect the genesis anchor:

```bash
cat samples/genesis.json
```

---

## Step 3 — Inspect the Reference Verifier

```bash
cat reference-verifier/src/verifier.py
```

The verifier performs three sequential checks:

1. JCS normalization + single RPU payload hash integrity
2. PrevHash chain continuity across all records
3. HACS cryptographic signature verification *(v0.2 planned)*

> **Live execution of the verifier is pending Phase 1 infrastructure deployment.**
> Once deployed, running the verifier against the sample chain will produce:
>
> ```
> RESULT: ALL PASS
> anchor_hash: 3BAC33BE74B76B2AED83BE6C3594C7F08D3C9E889ABB9F0B97FD39BFD9E52C14
> ```

---

## Step 4 — Manually Recompute a Single RPU Hash

You can verify the hash chain formula directly with Python:

```python
import hashlib

# Hash chain formula: SHA256(prev_hash || 0x00 || payload_c14n)
payload_c14n = b'...'      # JCS-normalized payload bytes
prev_hash    = bytes(32)   # 32 zero-bytes for genesis RPU

digest = hashlib.sha256(prev_hash + b'\x00' + payload_c14n).hexdigest()
print(digest)
```

The v0.1 anchor hash derived from the protocol specification:

```
3BAC33BE74B76B2AED83BE6C3594C7F08D3C9E889ABB9F0B97FD39BFD9E52C14
```

This value will be independently recomputable from the sample chain
once the reference verifier is deployed in Phase 1.

---

## What This Protocol Guarantees

When Phase 1 is complete, any party will be able to independently verify that:

1. Each RPU's payload was not altered (payload_hash check)
2. The chain was not broken or reordered (chain_hash check)
3. The governance process is structurally intact

No trust in AIBA required. The math speaks for itself.

---

## Next Steps

- Read the full specification: [`DESIGN.md`](./DESIGN.md)
- Explore the verifier source: [`reference-verifier/src/verifier.py`](./reference-verifier/src/verifier.py)
- Open an issue or submit a pull request

---

*"Governance is not declared. It is recomputed."*
