# ARSS Quick Start

Recompute a governance chain in under 5 minutes.

---

## Prerequisites

- Python 3.8+
- No external dependencies required

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/aiba-global/arss-protocol.git
cd arss-protocol
```

---

## Step 2 — Inspect the Sample Chain

The `samples/` directory contains a pre-verified 3-event chain from the Law & Compliance domain:

```
samples/
├── genesis.json            ← Chain start anchor
├── rpu-001-ai-output.json  ← AI_OUTPUT_GENERATED
├── rpu-002-human-review.json  ← HUMAN_REVIEW_LOGGED
└── rpu-003-human-approval.json ← HUMAN_APPROVAL_RECORDED
```

This represents: AI drafts a legal document → attorney reviews → partner approves.

---

## Step 3 — Run the Reference Verifier

```bash
python reference-verifier/src/verifier.py samples/
```

You should see:

```
============================================================
ARSS Reference Verifier v0.1
============================================================
Genesis Anchor ... OK
RPU #1 (AI_OUTPUT_GENERATED)
  payload_hash  : PASS
  chain_hash    : PASS
RPU #2 (HUMAN_REVIEW_LOGGED)
  payload_hash  : PASS
  chain_hash    : PASS
RPU #3 (HUMAN_APPROVAL_RECORDED)
  payload_hash  : PASS
  chain_hash    : PASS
  hacs_signature: PRESENT (full verification requires public key)
============================================================
RESULT: ALL PASS
Final chain hash:
  3de51ae75318d7493fe7850046df41920e92362630a50a1a63af951adadf7763
============================================================
```

---

## Step 4 — Verify the Expected Hash

```bash
cat tests/expected-chain-hash.txt
```

Compare with the output above. If they match:

> **You have independently recomputed the ARSS governance chain.**
> **The recomputation produced the same result.**

This is Recomputable Governance.

---

## What Just Happened

You independently verified that:

1. Each RPU's payload was not altered (payload_hash check)
2. The chain was not broken or reordered (chain_hash check)
3. The governance process — AI output → human review → human approval — is structurally intact

No trust in AIBA required. The math speaks for itself.

---

## Next Steps

- Read the full specification: [`spec/ARSS-RPU-Spec-v0.1.md`](./spec/ARSS-RPU-Spec-v0.1.md)
- Dive deeper into specific topics:
  - [Genesis Anchor](./spec/genesis-anchor.md) — how a chain's cryptographic origin is established
  - [Schema Versioning](./spec/schema-versioning.md) — how RPU structure evolves over time
  - [Hash Algorithm Agility](./spec/hash-algorithm-agility.md) — how ARSS handles algorithm transitions
- Explore the verifier source: [`reference-verifier/src/verifier.py`](./reference-verifier/src/verifier.py)
- Run the test suite: `python -m pytest reference-verifier/tests/`
