# ARSS Design Rationale

This document explains why ARSS exists, what it guarantees, and what it explicitly does not guarantee. It is intended for infrastructure engineers evaluating whether ARSS is appropriate for a given use case.

---

## 1. Introduction

### Why ARSS Exists

AI systems are increasingly involved in consequential decisions — decisions about people, resources, and risk. Organizations deploying these systems are expected to demonstrate that governance controls were applied: that policies were followed, that human actors reviewed outputs, that accountability was maintained.

The problem is structural. Most governance evidence today takes one of two forms:

- **Declared records** — policy documents, audit reports, compliance statements that assert governance occurred
- **System logs** — append-only event streams that record what happened but are not designed to support independent verification of governance intent

Neither form produces a record that a third party can independently verify without access to the originating system or the organization's cooperation.

ARSS exists to fill this gap.

### The Problem of Unverifiable Governance Records

A governance record that cannot be independently verified is, in a strict sense, only an assertion. It may be accurate. It may not be. A third party — auditor, regulator, court — has no structural basis to distinguish between a genuine record and a post-hoc reconstruction.

ARSS converts governance events into Record Proof Units (RPUs): deterministically serialized, cryptographically chained records that any third party can recompute from raw data alone, without depending on the originating system, its infrastructure, or its cooperation.

The central design goal is this: **verification must be possible without trust**.

---

## 2. What ARSS Is Not

Before describing what ARSS provides, it is necessary to distinguish it from existing systems that may appear structurally similar.

### 2.1 Not a Blockchain

At the surface level, ARSS and blockchain both use hash chains. The similarity ends there.

Blockchain solves a specific problem: achieving consensus on shared state among mutually untrusting parties in a distributed network. The hash chain in a blockchain is a mechanism for linking consensus results. The core technical component is not the hash chain — it is the consensus protocol (Proof of Work, Proof of Stake, or equivalent).

ARSS does not solve a distributed consensus problem. Governance decisions in an organizational context are made by a single authoritative actor. There is no disputed state to resolve across untrusting peers.

Applying a blockchain architecture to ARSS would introduce consensus overhead without improving the trust model. More importantly, it would compromise the property ARSS is designed to preserve: that any third party can recompute chain integrity from raw records alone, without participating in or depending on any network.

**Blockchain solves distributed consensus among untrusted parties. ARSS solves independently recomputable integrity for a single authoritative actor. These are different problems.**

### 2.2 Not a Transparency Log

Certificate Transparency, Sigstore Rekor, and Merkle-tree audit logs are well-designed systems. They solve a real problem: proving that a specific artifact (certificate, software signature, package) existed and was publicly logged at a given point in time. The core property they provide is inclusion proof — verifiable evidence that an artifact is part of a public log.

ARSS does not solve an artifact inclusion problem.

The unit of record in a transparency log is an artifact hash. The unit of record in ARSS is a governance event — a structured record of who made a decision, under which policy, with which authority, in which jurisdiction, and in what sequence relative to other decisions.

Transparency logs do not require governance context. They do not bind records to a human actor's cryptographic signature. They do not embed policy identity or jurisdictional authority as required fields. Their design goal — public, append-only artifact logging for public infrastructure — is structurally different from the goal of producing recomputable evidence of organizational governance decisions.

Additionally, verification of existing transparency logs depends on log server availability. ARSS verification requires only the raw record files and a reference verifier. This distinction matters in environments where verification must be independent of external infrastructure.

**Transparency logs prove that an artifact existed. ARSS proves that a governance decision was made by a specific actor, under a specific policy, in a verifiable sequence — recomputable without depending on any external service.**

### 2.3 Not a Truth Guarantee

This is the most important limitation to state clearly.

ARSS guarantees **post-hoc structural integrity**: that a record has not been modified after it was created. ARSS does not guarantee **ante-hoc factual truth**: that the record was accurate at the moment it was created.

No cryptographic system provides this guarantee. SHA256 does not validate the truthfulness of its input. It validates that the input has not changed. A hash of a false statement is as cryptographically valid as a hash of a true one.

An organization that records a false governance event into an ARSS chain will produce a chain with valid structural integrity. The chain will pass verification. The underlying record may still be false.

This is not a design flaw unique to ARSS. It is the fundamental boundary between cryptographic integrity and epistemic truth — a boundary that applies to every logging and audit system.

What ARSS does provide, however, is that any false record, once committed:

- Cannot be quietly altered or retracted
- Remains permanently attributed to a specific human actor via HACS
- Is bound to a declared policy context, authority root, and jurisdiction
- Is structurally traceable across the chain in which it appears

Falsifying a record in ARSS is not technically impossible. It is structurally traceable and legally attributable. In audit, regulatory, and litigation environments, that distinction — between a lie that can be quietly corrected and a lie that is permanently signed and attributed — is operationally significant.

**ARSS does not prevent false records. It makes false records permanently attributed and structurally traceable.**

---

## 3. What ARSS Guarantees

### 3.1 Post-hoc Structural Integrity

Once a governance event is committed as an RPU, it cannot be modified without breaking the chain. Each RPU embeds the hash of the previous record:

```
SHA256(prev_hash || 0x00 || payload_c14n)
```

Any modification to any record in the chain — including past records — produces a hash mismatch detectable by the reference verifier. The chain is tamper-evident from any point of modification forward.

### 3.2 Independent Recomputability

Verification requires only two things: the raw record files and a reference verifier. No network connection, no log server, no access to the originating system.

This property is not incidental. It is a primary design requirement. Governance verification in audit, regulatory, and litigation contexts must be executable by an independent third party without depending on the cooperation or infrastructure of the party being audited.

Any verifier that implements the three-step verification protocol — JCS normalization, hash chain continuity, HACS verification — will produce identical results on identical inputs, regardless of environment.

### 3.3 Actor Attribution

Each RPU includes an `actor_id` — a deterministic identifier derived from the actor's public key. HACS (Human Actor Cryptographic Signature) binds the governance decision to a specific human actor at the time of commitment.

This is structurally distinct from a system log that records what happened. ARSS records who was accountable for a decision, and cryptographically binds that attribution to the record.

In AI governance contexts, where automated systems may generate outputs that feed into human decisions, the HACS requirement establishes a clear structural record of where human accountability begins.

### 3.4 Governance Context

Each RPU includes a `governance_context` object with three required fields:

- **Policy ID** — the specific policy under which the decision was made
- **Authority Root** — the organizational authority structure applicable to the decision
- **Jurisdiction** — the regulatory or legal jurisdiction governing the decision

These fields are not metadata. They are required structural components of the record. A governance event recorded without this context does not constitute a valid RPU.

This design reflects the difference between a system log and a governance record. A system log records events. A governance record records decisions in context. Context is what makes a record defensible in an audit or regulatory proceeding — not just the fact that something happened, but the policy framework under which it was governed.

---

## 4. Why These Properties Matter

### Audit Environments

Auditors require evidence that is independently verifiable, tamper-evident, and attributable. Audit findings challenged in subsequent proceedings must be defensible on the basis of the record itself, not the auditor's access to the originating system.

ARSS produces records that satisfy these requirements structurally. A chain that passes three-step verification — JCS normalization, hash chain continuity, HACS — provides a basis for audit findings that does not depend on the ongoing cooperation of the audited party.

### Regulatory Oversight

Regulatory oversight of AI systems increasingly requires organizations to demonstrate, not merely assert, that governance controls were applied. Declarations are insufficient when regulators require evidence that can survive independent scrutiny.

ARSS provides a record format designed for this purpose: governance context embedded as required fields, actor attribution cryptographically bound, chain integrity independently recomputable.

### Litigation and Evidence Chains

Evidence introduced in litigation must be authenticated. A record whose integrity can be verified by any party with the raw files and a reference implementation is structurally more defensible than a record whose authenticity depends on the producing party's cooperation.

The permanent attribution property of ARSS is particularly relevant in contested proceedings. A governance record that cannot be quietly retracted or corrected, and whose author is cryptographically identified, changes the evidentiary posture of governance documentation.

### AI Governance Accountability

As AI systems move from tools to autonomous agents, the question of where human accountability resides becomes structurally ambiguous. ARSS provides one component of an answer: a record format that requires human actor attribution at each governance decision point, and that makes the sequence and context of those decisions independently verifiable.

ARSS does not resolve all questions of AI accountability. It provides structural evidence that human governance decisions were made, by whom, under which policy, and in what sequence — evidence that can be verified by any third party without depending on the organization that produced it.

---

## 4a. Architecture: Current Scope and Extension Points

### v0.1 — Hash-Chain Protocol (Current Public Scope)

ARSS v0.1 defines a governance evidence protocol based on recomputable hash chains. The following components are fully specified and publicly documented:

- Governance event record (RPU) with required fields
- Hash-chain construction: `SHA256(prev_hash || 0x00 || payload_c14n)`
- JCS normalization (RFC 8785) for deterministic serialization
- Reference verifier (Python, single-file, no external dependencies beyond `cryptography`)
- Sample chain with known anchor hash

### HACS — Hash-Anchored Cryptographic Signatures

**Status: Implemented — public specification: v0.2 planned**

HACS is the signature verification layer that binds human actor identity to governance records via cryptographic signatures. The reference verifier includes HACS verification logic. The public key specification, key management guidelines, and trust anchor architecture are scoped to v0.2.

```
v0.1  hash-chain governance evidence protocol   ← current public scope
v0.2  HACS: Hash-Anchored Cryptographic Signatures ← public spec planned
```

Architecture position:

```
arss-protocol/
├── spec/                    ← v0.1 public specification
├── reference-verifier/      ← HACS logic implemented, spec v0.2
└── samples/                 ← hash-chain verification only
```

Separate repository candidate: `arss-hacs` (future, post v0.2 spec release)

---

## 5. Design Principles

**Recomputable, not trusted.**
Any claim about chain integrity must be verifiable from raw records alone. Verification that requires trusting a server, a network, or an organization is not independent verification.

**Deterministic, not environment-dependent.**
JCS normalization (RFC 8785) ensures that the same governance event produces identical byte sequences on any machine, in any environment. A hash that varies by environment is not a reliable integrity proof.

**Traceable, not unverifiable.**
ARSS does not eliminate the possibility of false records. It eliminates the possibility of false records that are unattributed, untraceable, or quietly correctable. Traceability is the structural property that makes governance records defensible — not the impossibility of error.

---

## Appendix: Standard Responses for Technical Discussions

The following responses are derived from this document for use in developer discussions.

**"Why not just use a blockchain?"**
> Blockchain solves distributed consensus among untrusted parties. ARSS solves independently recomputable integrity for a single authoritative actor. A governance record doesn't need network agreement — it needs to be verifiable from raw data alone, without trusting any infrastructure. Blockchain would add consensus overhead while removing the property we need most: that any third party can recompute the record without depending on any network or node.

**"Why not just use a transparency log?"**
> Transparency logs prove that an artifact existed. ARSS proves that a governance decision was made by a specific actor, under a specific policy, in a verifiable sequence — and that any third party can recompute that proof from raw records alone, without depending on a log server. The unit of record is not a hash of an artifact but a structured governance event with mandatory context fields. That's a different problem.

**"If the organization lies when recording events, how does ARSS help?"**
> ARSS doesn't prevent lying at the time of recording. No cryptographic system does — SHA256 doesn't validate truth, it validates integrity. What ARSS provides is that any lie, once recorded and signed under HACS, becomes permanently attributed to a specific actor under a specific policy context. The record cannot be quietly corrected later. Lying becomes structurally traceable, not structurally impossible. In audit and litigation environments, that distinction matters.

---

*ARSS protocol development is initiated by AIBA Global. The protocol specification is independent of AIBA's commercial infrastructure.*
