"""
AIBA MCP Nonce Store  v1.0.0
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C
EAG:   EAG-2 비오(Joshua) 승인 (S128)
설계:  도미 PHASE-C FINAL ANCHOR (S128)

책임:
- single-use nonce 관리
- TTL 15분 기준 만료 처리
- replay 방지
"""

import threading
import time

# TTL: 15분 (초 단위)
NONCE_TTL_SECONDS = 900


class NonceStore:
    """
    in-memory nonce 저장소.
    TTL 내 사용된 nonce를 추적하여 replay 방지.
    프로세스 재시작 시 초기화됨 — TA-R1 기준 timestamp ±60초 검증으로 보완.
    """

    def __init__(self, ttl_seconds: int = NONCE_TTL_SECONDS):
        self._store: dict[str, float] = {}  # nonce → 등록 시각(epoch)
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def is_used(self, nonce: str) -> bool:
        """nonce가 이미 사용된 경우 True 반환."""
        self._evict_expired()
        with self._lock:
            return nonce in self._store

    def mark_used(self, nonce: str) -> bool:
        """
        nonce를 사용 처리.
        이미 사용된 경우 False 반환 (replay 감지).
        신규 nonce이면 등록 후 True 반환.
        """
        self._evict_expired()
        with self._lock:
            if nonce in self._store:
                return False
            self._store[nonce] = time.time()
            return True

    def _evict_expired(self) -> None:
        """TTL 만료된 nonce 제거."""
        now = time.time()
        with self._lock:
            expired = [n for n, t in self._store.items() if now - t > self._ttl]
            for n in expired:
                del self._store[n]

    def size(self) -> int:
        """현재 저장된 nonce 수 (테스트용)."""
        self._evict_expired()
        with self._lock:
            return len(self._store)

    def clear(self) -> None:
        """전체 초기화 (테스트용)."""
        with self._lock:
            self._store.clear()


# 모듈 레벨 싱글턴
_nonce_store = NonceStore()


def is_nonce_used(nonce: str) -> bool:
    return _nonce_store.is_used(nonce)


def consume_nonce(nonce: str) -> bool:
    """nonce 소비. 성공(신규) = True / 실패(재사용) = False."""
    return _nonce_store.mark_used(nonce)


def clear_nonce_store() -> None:
    """테스트 전용 초기화."""
    _nonce_store.clear()


def nonce_store_size() -> int:
    """테스트 전용 크기 조회."""
    return _nonce_store.size()
