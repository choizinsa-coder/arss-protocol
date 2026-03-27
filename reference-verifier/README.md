# Sample Reference Verifier v0.1-Alpha

> ⚠️ **Position Notice**
> This verifier is a **Sample Reference Verifier** for educational and demo purposes only.
> It is **NOT** the production verifier for the ARSS governance chain.
> Production verification is handled by `vps_verifier_bridge.py v0.2` (running on VPS).

---

## Position

| Item | Detail |
|---|---|
| Official Name | Sample Reference Verifier v0.1-Alpha |
| Position | Educational / Sample / Demo — NOT for Production use |
| Target Chain | `samples/` (RPU-0004 ~ RPU-0008) |
| Algorithm | Legacy: JCS / `0x00` separator |
| Production Verifier | `vps_verifier_bridge.py v0.2` (VPS 159.203.125.1) |
| Basis | ARSS-RPU-Production-Spec-v1.0 / LESSON-005 |

---

## Sample Chain Overview

This directory contains the **ARSS sample chain** (RPU-0004 ~ RPU-0008).
All records are independently recomputable. No trust required.

| RPU ID | Event Type | State | Chain Hash (first 16 chars) |
|---|---|---|---|
| RPU-0004 | GOVERNANCE_EVENT | STATE-001 | `dcb3b378afdd5a41` |
| RPU-0005 | DECISION | STATE-001 | `db273fa39267a93c` |
| RPU-0006 | APPROVAL | STATE-001 | `ad0a2fdf6fe2f3e2` |
| RPU-0007 | EXECUTION | STATE-002 | `82d6606293e2fe69` |
| RPU-0008 | EVIDENCE | STATE-002 | `3fa890300b41871f` |

**Sample Chain Tip (RPU-0008):**
```
3fa890300b41871f9e3aa0ed0d6b8463231bb75efba9dd250bccdf3e3e572c52
```

---

## How to Verify (Sample Chain)

Requires: Python 3, standard library only.

### Step 1 — Recompute payload_hash

```python
import hashlib, json

def canonical_json(obj):
    if isinstance(obj, dict):
        return '{' + ','.join(
            f'{canonical_json(k)}:{canonical_json(v)}'
            for k, v in sorted(obj.items())
        ) + '}'
    if isinstance(obj, list):
        return '[' + ','.join(canonical_json(i) for i in obj) + ']'
    if isinstance(obj, bool):
        return 'true' if obj else 'false'
    if isinstance(obj, (int, float)):
        return str(obj)
    return json.dumps(obj, ensure_ascii=False)

with open('rpu-0004.json') as f:
    rpu = json.load(f)

payload_hash = hashlib.sha256(
    canonical_json(rpu['payload']).encode('utf-8')
).hexdigest()
assert payload_hash == rpu['chain']['payload_hash'], "payload_hash FAIL"
print("payload_hash:", payload_hash)
```

### Step 2 — Recompute chain_hash

```python
chain_input = rpu['chain']['prev_hash'] + ':' + payload_hash
chain_hash = hashlib.sha256(chain_input.encode('utf-8')).hexdigest()
assert chain_hash == rpu['chain']['chain_hash'], "chain_hash FAIL"
print("chain_hash:", chain_hash)
```

### Step 3 — Verify full chain continuity

```python
files = ['rpu-0004.json','rpu-0005.json','rpu-0006.json','rpu-0007.json','rpu-0008.json']
prev = None
for fname in files:
    with open(fname) as f:
        rpu = json.load(f)
    ph = hashlib.sha256(canonical_json(rpu['payload']).encode()).hexdigest()
    ch = hashlib.sha256((rpu['chain']['prev_hash'] + ':' + ph).encode()).hexdigest()
    assert ph == rpu['chain']['payload_hash']
    assert ch == rpu['chain']['chain_hash']
    if prev:
        assert rpu['chain']['prev_hash'] == prev
    prev = ch
    print(f"{rpu['rpu_id']}: PASS — {ch[:16]}...")
print("Chain Tip:", prev)
```

---

## Hash Calculation Rules

- **Canonicalization:** Keys sorted alphabetically, recursive, minified, no whitespace
- **payload_hash:** `SHA256(canonical_json(payload))` → lowercase hex
- **chain_hash:** `SHA256(prev_hash + ":" + payload_hash)` → lowercase hex, UTF-8 input
- **No external dependencies.** SHA256 + JSON only.

---

## Files

| File | Description |
|---|---|
| `rpu-0004.json` | Genesis governance event |
| `rpu-0005.json` | Production chain transition decision |
| `rpu-0006.json` | Official approval — STATE-001 |
| `rpu-0007.json` | Operational execution — Internal Proof PASS |
| `rpu-0008.json` | Evidence seal — STATE-001 complete, STATE-002 activated |
| `ledger.json` | Full chain index with state history |

---

## ❌ Prohibited Uses

- Using this verifier on the Production chain (RPU-0009~)
- Treating this verifier's algorithm as the Production standard
- Publishing PASS/FAIL results from this verifier as Production trust evidence

> Violation triggers **LESSON-005** — Production chain ALL FAIL.

---

## Production Chain Verification

The Production chain (RPU-0009 ~ RPU-0012) is publicly available in `evidence/`.

To verify independently:

```bash
# On VPS
cd /opt/arss/engine/arss-protocol
python3 vps_verifier_bridge.py

# Expected output:
# RPU-0009: PASS
# RPU-0010: PASS
# RPU-0011: PASS
# RPU-0012: PASS
# RESULT: ALL PASS
# Final chain hash: 3a97b31b09c7bdfe7a4c22eb7713459a2c2d25e2e9bca588b9f572a0e9445839
```

**Production Chain Tip (RPU-0012):**
```
3a97b31b09c7bdfe7a4c22eb7713459a2c2d25e2e9bca588b9f572a0e9445839
```

---

*ARSS Protocol — Accountability Record & Structural Signature*
*AIBA Global Project | github.com/choizinsa-coder/arss-protocol*
