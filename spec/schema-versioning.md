# Schema Versioning Specification

**ARSS RPU Specification v0.1 — Supplementary Document**

---

## 1. Purpose

As ARSS evolves, RPU structure will change — new fields added, existing fields refined, event types introduced. Schema Versioning ensures that every RPU explicitly declares which version of the RPU schema it conforms to, enabling verifiers to apply the correct validation rules and maintaining chain integrity across protocol generations.

---

## 2. Version Format

### 2.1 Version String

The RPU `version` field uses the format:

```
rpu/<major>.<minor>
```

| Component | Meaning | Example |
|---|---|---|
| Prefix | Fixed literal `rpu/` — identifies this as an RPU schema version | `rpu/` |
| Major | Breaking changes. Increment when backward compatibility is broken | `1`, `2` |
| Minor | Additive changes. Increment when new optional fields or event types are added | `0`, `1`, `3` |

Current version: **`rpu/1.0`**

### 2.2 Examples

| Version | Meaning |
|---|---|
| `rpu/1.0` | Initial release. v0.1 specification |
| `rpu/1.1` | Additive change — e.g., new optional payload field |
| `rpu/1.2` | Another additive change — e.g., new event type added |
| `rpu/2.0` | Breaking change — e.g., required field renamed or hash formula changed |

---

## 3. Compatibility Rules

### 3.1 Backward Compatibility (Minor Version Changes)

A minor version increment MUST be backward compatible. Specifically:

- **New optional fields** may be added to RPU or payload structures.
- **New event types** may be introduced.
- **Existing required fields** must not be removed, renamed, or have their semantics changed.
- **Hash computation rules** must not change.
- **JCS serialization rules** must not change.

A verifier built for `rpu/1.0` MUST be able to verify any `rpu/1.x` RPU by ignoring unknown fields. Unknown fields do not participate in hash computation unless explicitly declared in the version's specification addendum.

### 3.2 Breaking Changes (Major Version Changes)

A major version increment signals that backward compatibility is broken. This includes:

- Renaming or removing a required field
- Changing the hash computation formula
- Changing the canonical serialization standard
- Altering the `chain_hash` derivation
- Changing the Genesis Anchor structure

Breaking changes require a **chain migration event** (see Section 5).

### 3.3 Compatibility Matrix

| Verifier Version | RPU `rpu/1.0` | RPU `rpu/1.1` | RPU `rpu/2.0` |
|---|---|---|---|
| `rpu/1.0` verifier | ✅ Full | ✅ Ignore unknown fields | ❌ Cannot verify |
| `rpu/1.1` verifier | ✅ Full | ✅ Full | ❌ Cannot verify |
| `rpu/2.0` verifier | ⚠️ Legacy mode | ⚠️ Legacy mode | ✅ Full |

---

## 4. Version in RPU Records

### 4.1 Field Placement

Every RPU record MUST include `version` as a top-level required field:

```json
{
  "rpu_id": "01956a20-0000-7000-8000-000000000001",
  "version": "rpu/1.0",
  "timestamp": "2026-03-06T09:00:00.000000Z",
  ...
}
```

### 4.2 Version Consistency Within a Chain

RPUs within the same chain MAY have different minor versions. For example, a chain may start with `rpu/1.0` records and later include `rpu/1.1` records after a specification update.

RPUs within the same chain MUST NOT have different major versions without a chain migration event (see Section 5).

### 4.3 Version in Hash Computation

The `version` field is a top-level RPU field, NOT part of the `payload` object. It is therefore NOT included in `payload_hash` computation.

The `version` field IS included when computing the full RPU record hash for archival or external anchoring purposes (future specification).

---

## 5. Chain Migration (Major Version Transition)

When a major version change occurs, existing chains cannot seamlessly continue because the hash computation rules differ. The following migration procedure applies:

### 5.1 Migration Event

A special `CHAIN_MIGRATION` event is appended to the existing chain under the **old** major version. This event:

- Records the intent to migrate
- Contains the final `chain_hash` under the old version
- References the new chain's `chain_id` (created under the new major version)

```json
{
  "event_type": "CHAIN_MIGRATION",
  "version": "rpu/1.x",
  "payload": {
    "migration_target_version": "rpu/2.0",
    "new_chain_id": "<new-chain-uuid>",
    "final_chain_hash": "<last-chain-hash-under-v1>",
    "migration_reason": "Major version upgrade to rpu/2.0"
  }
}
```

### 5.2 New Chain Genesis

A new Genesis Anchor is created for the `rpu/2.0` chain. The new genesis `input` SHOULD include a `migrated_from` field:

```json
{
  "chain_id": "<new-chain-uuid>",
  "protocol": "ARSS",
  "version": "2.0",
  "timestamp": "...",
  "migrated_from": {
    "chain_id": "<old-chain-uuid>",
    "final_chain_hash": "<last-chain-hash-under-v1>"
  }
}
```

### 5.3 Audit Continuity

Both chains remain valid and verifiable under their respective versions. An auditor can trace the full history by following the migration link from the new chain's genesis back to the old chain's final state.

---

## 6. Version Negotiation (Future)

For v0.1, version management is manual — the producing system sets the `version` field based on the specification it implements.

Future versions may define:

- **Version advertisement:** A mechanism for systems to declare supported RPU versions
- **Minimum version requirements:** Per-chain or per-policy minimum version enforcement
- **Deprecation timeline:** Formal process for retiring old minor versions

These are out of scope for v0.1.

---

## 7. Implementation Notes

### 7.1 Verifier Behavior

The Reference Verifier MUST:

1. **Read** the `version` field of each RPU before validation
2. **Check** that the version is within its supported range
3. **Apply** version-appropriate validation rules
4. **Report** unsupported versions clearly (not silently ignore)

### 7.2 Version Registration

v0.1 defines a single version: `rpu/1.0`. New versions will be documented as addenda to this specification or as new specification documents in the `spec/` directory.

| Version | Status | Document |
|---|---|---|
| `rpu/1.0` | Active | This document |

---

*ARSS Schema Versioning Specification — AIBA Global Project*
