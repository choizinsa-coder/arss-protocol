from hashlib import sha256


def sha256_full_raw_content(content: bytes) -> str:
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    normalized = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return sha256(normalized.encode("utf-8")).hexdigest()
