# RULE-8 ASSERTION — S181 Batch-11B
# Module: mcp_nonce_store
# Task: P4-C4 Phase-beta Batch-11B
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest
import time


def _get_store():
    """격리된 NonceStore 인스턴스 반환 (모듈 싱글턴 오염 방지)."""
    from tools.mcp.mcp_nonce_store import NonceStore
    return NonceStore(ttl_seconds=900)


def test_nonce_consume_rejects_reused_nonce():
    """이미 사용된 nonce를 consume_nonce로 재사용 시 False 반환."""
    store = _get_store()
    nonce = "test-nonce-reuse-001"
    assert store.mark_used(nonce) is True   # 최초 등록 → True
    assert store.mark_used(nonce) is False  # 재사용 → False


def test_nonce_is_used_returns_true_after_consume():
    """consume 후 is_used가 True를 반환해야 한다."""
    store = _get_store()
    nonce = "test-nonce-is-used-002"
    store.mark_used(nonce)
    assert store.is_used(nonce) is True


def test_nonce_unknown_nonce_is_not_marked_used():
    """등록되지 않은 nonce는 is_used가 False를 반환해야 한다."""
    store = _get_store()
    assert store.is_used("never-registered-nonce-003") is False


def test_nonce_expired_nonce_is_evicted():
    """TTL 0초 store에서 등록 후 즉시 evict — 만료 nonce는 재사용으로 처리되지 않는다."""
    from tools.mcp.mcp_nonce_store import NonceStore
    store = NonceStore(ttl_seconds=0)
    nonce = "test-nonce-ttl-004"
    store.mark_used(nonce)
    # TTL=0 이므로 evict 후 is_used=False (만료로 삭제됨)
    time.sleep(0.01)
    assert store.is_used(nonce) is False
