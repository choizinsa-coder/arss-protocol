import hashlib
import json


def normalize_text(s: str) -> str:
    """Normalize newlines to LF."""
    return s.replace('\r\n', '\n').replace('\r', '\n')


def normalize_json(obj) -> str:
    """Deterministic JSON: sort_keys=True, separators=(',',':'), ensure_ascii=False."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def compute_hash(data) -> str:
    """SHA256 hex. Normalization enforced — raises ValueError for unsupported types."""
    if isinstance(data, dict):
        encoded = normalize_json(data).encode('utf-8')
    elif isinstance(data, str):
        encoded = normalize_text(data).encode('utf-8')
    elif isinstance(data, bytes):
        encoded = data
    else:
        raise ValueError("INVALID: hash computed without normalization")
    return hashlib.sha256(encoded).hexdigest()
