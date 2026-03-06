# ARSS Protocol Specification

This directory contains the formal specification documents for the ARSS protocol.

---

## Documents

| Document | Description |
|---|---|
| [ARSS-RPU-Spec-v0.1.md](./ARSS-RPU-Spec-v0.1.md) | **Core specification.** RPU structure, hash chain rules, event model, verification process. Start here |
| [genesis-anchor.md](./genesis-anchor.md) | Chain origin rules. How the cryptographic trust root is established and verified |
| [schema-versioning.md](./schema-versioning.md) | RPU version management. Backward compatibility rules and chain migration procedure |
| [hash-algorithm-agility.md](./hash-algorithm-agility.md) | Post-SHA256 transition strategy. Dual-hash operation and algorithm migration phases |

## Reading Order

1. **Core spec** first — understand RPU fields, hash formulas, and the three-step verification
2. **Genesis Anchor** — how chains begin and why the starting point matters
3. **Schema Versioning** and **Hash Algorithm Agility** — how the protocol evolves without breaking existing chains

---

## Version

Current: **v0.1 — DRAFT**

Specification license: [CC BY 4.0](../LICENSE-SPEC)

---

*AIBA Global Project*
