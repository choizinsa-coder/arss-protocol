# ARSS — Accountability Record & Structural Signature

> **Governance is not declared. It is recomputed.**

ARSS is a **governance verification infrastructure** — not an AI system, not a governance policy, but the infrastructure that makes governance decisions independently verifiable.

Any AI decision chain recorded with ARSS can be recomputed by anyone, at any time, producing the same cryptographic result.

---

## What This Repository Provides

| Resource | Description |
|---|---|
| [`spec/`](./spec/) | Protocol specification documents |
| &nbsp;&nbsp;[`ARSS-RPU-Spec-v0.1.md`](./spec/ARSS-RPU-Spec-v0.1.md) | RPU v0.1 Specification — the core protocol definition |
| &nbsp;&nbsp;[`genesis-anchor.md`](./spec/genesis-anchor.md) | Genesis Anchor — chain origin rules and trust root |
| &nbsp;&nbsp;[`schema-versioning.md`](./spec/schema-versioning.md) | Schema Versioning — RPU version management and migration |
| &nbsp;&nbsp;[`hash-algorithm-agility.md`](./spec/hash-algorithm-agility.md) | Hash Algorithm Agility — post-SHA256 transition path |
| [`reference-verifier/`](./reference-verifier/) | Official reference implementation of the spec |
| [`samples/`](./samples/) | Pre-verified sample chain (Law & Compliance domain) |
| [`tests/`](./tests/) | Expected outputs for independent reproduction |

---

## Core Concept

An ARSS chain records three governance events in sequence:

```
AI_OUTPUT_GENERATED  →  HUMAN_REVIEW_LOGGED  →  HUMAN_APPROVAL_RECORDED
```

Each event is linked by a cryptographic hash chain:

```
chain_hash = SHA256( prev_hash || 0x00 || payload_hash )
payload_hash = SHA256( JCS( payload ) )
```

Anyone can recompute this chain from scratch and verify that no record has been altered.

---

## Quick Start

```bash
git clone https://github.com/aiba-global/arss-protocol.git
cd arss-protocol
python reference-verifier/src/verifier.py samples/
```

Expected final chain hash:
```
3de51ae75318d7493fe7850046df41920e92362630a50a1a63af951adadf7763
```

See [QUICKSTART.md](./QUICKSTART.md) for step-by-step instructions.

---

## Design Principles

**1. Recomputable Governance**
Every governance record can be independently recomputed. Trust is structural, not declarative.

**2. Event Immutability**
Once written, an RPU payload is never modified. Corrections are new events, appended to the chain.

**3. Infrastructure, Not Certification**
ARSS provides the verification infrastructure. Auditors and certifiers remain independent third parties.

**4. Natural Lock-in via Chain Continuity**
The `prev_hash` chain structure means switching systems breaks chain continuity — a structural property, not an artificial barrier.

---

## Protocol Stack

```
Concept  :  Recomputable Governance
Protocol :  ARSS (Accountability Record & Structural Signature)
Record   :  RPU (Record Proof Unit)
Chain    :  SHA256 hash chain with JCS canonicalization
```

---

## Status

| Item | Status |
|---|---|
| Event Model v0.1 | ✅ Defined |
| RPU Specification v0.1 | ✅ Draft complete |
| Independent recomputation test | ✅ ALL PASS |
| Reference Verifier CLI | 🔧 In progress |
| GitHub public release | 🔧 In preparation |
| First pilot (Law & Compliance) | 📋 Planned |

---

## License

Specification: [CC BY 4.0](./LICENSE-SPEC)
Reference Verifier: [Apache 2.0](./LICENSE)

---

*AIBA Global Project — [aiba.global](https://aiba.global)*
