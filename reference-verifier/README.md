# ARSS Reference Verifier

Official reference implementation of the ARSS RPU Specification v0.1.

This is not just a verification tool — it is the **spec-driven reference implementation**.
When other developers build ARSS implementations, this verifier is the standard they test against.

## Usage

```bash
python src/verifier.py <samples_dir>
python src/verifier.py ../../samples/
```

## What It Verifies

1. **Genesis Anchor integrity** — SHA256(JCS(genesis_input)) matches declared hash
2. **payload_hash** — SHA256(JCS(payload)) matches declared value per RPU
3. **prev_hash continuity** — each RPU's prev_hash links correctly to the prior chain_hash
4. **chain_hash** — SHA256(prev_hash_bytes || 0x00 || payload_hash_bytes) recomputed
5. **HACS signature presence** — checked for HUMAN_APPROVAL_RECORDED events

## No External Dependencies

Python 3.8+ standard library only (`hashlib`, `json`, `sys`, `os`, `pathlib`).
