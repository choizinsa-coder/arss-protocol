# ARSS Protocol — Sample Chain

This directory contains the AIBA OS v0.1 Production Chain (RPU-0004 ~ RPU-0008).

All records are independently recomputable. No trust required.

---

## Chain Overview

| RPU ID   | Event Type      | State        | Chain Hash (first 16 chars) |
|----------|-----------------|--------------|------------------------------|
| RPU-0004 | GOVERNANCE_EVENT | STATE-001   | `dcb3b378afdd5a41`           |
| RPU-0005 | DECISION         | STATE-001   | `db273fa39267a93c`           |
| RPU-0006 | APPROVAL         | STATE-001   | `ad0a2fdf6fe2f3e2`           |
| RPU-0007 | EXECUTION        | STATE-002   | `82d6606293e2fe69`           |
| RPU-0008 | EVIDENCE         | STATE-002   | `3fa890300b41871f`           |

**Chain Tip (RPU-0008):**
```
3fa890300b41871f9e3aa0ed0d6b8463231bb75efba9dd250bccdf3e3e572c52
```

---

## How to Verify

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
|------|-------------|
| `rpu-0004.json` | Genesis governance event |
| `rpu-0005.json` | Production chain transition decision |
| `rpu-0006.json` | Official approval — STATE-001 |
| `rpu-0007.json` | Operational execution — Internal Proof PASS |
| `rpu-0008.json` | Evidence seal — STATE-001 complete, STATE-002 activated |
| `ledger.json`   | Full chain index with state history |

---

*ARSS Protocol — Accountability Record & Structural Signature*
*github.com/choizinsa-coder/arss-protocol*
