import pytest
from tools.session_context_gen.hash_utils import normalize_text, normalize_json, compute_hash


def test_normalize_text_crlf():
    assert normalize_text("a\r\nb") == "a\nb"


def test_normalize_text_cr():
    assert normalize_text("a\rb") == "a\nb"


def test_normalize_text_lf_unchanged():
    assert normalize_text("a\nb") == "a\nb"


def test_normalize_json_sorted_keys():
    result = normalize_json({"b": 1, "a": 2})
    assert result == '{"a":2,"b":1}'


def test_normalize_json_no_spaces():
    result = normalize_json({"k": "v"})
    assert " " not in result


def test_compute_hash_str_returns_64_hex():
    h = compute_hash("hello")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_hash_dict_returns_64_hex():
    h = compute_hash({"key": "val"})
    assert len(h) == 64


def test_compute_hash_bytes_returns_64_hex():
    h = compute_hash(b"hello")
    assert len(h) == 64


def test_compute_hash_int_raises():
    with pytest.raises(ValueError, match="INVALID: hash computed without normalization"):
        compute_hash(12345)


def test_compute_hash_none_raises():
    with pytest.raises(ValueError, match="INVALID: hash computed without normalization"):
        compute_hash(None)


def test_compute_hash_dict_deterministic():
    h1 = compute_hash({"b": 2, "a": 1})
    h2 = compute_hash({"a": 1, "b": 2})
    assert h1 == h2


def test_compute_hash_normalizes_crlf():
    h1 = compute_hash("line1\r\nline2")
    h2 = compute_hash("line1\nline2")
    assert h1 == h2
