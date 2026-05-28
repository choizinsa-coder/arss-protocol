"""
AIBA MCP Nonce Store  v1.0.1
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C + Recovery Governance Layer
EAG:   EAG-2 비오(Joshua) 승인 (S128) / EAG-3 비오(Joshua) 승인 (S130)

변경 이력:
- v1.0.0 (S128): 최초 구현
- v1.0.1 (S130): HC-T-02 (nonce replay) -> HARD_CONTAINMENT 진입 추가

책임:
- single-use nonce 관리
- TTL 15분 기준 만료 처리
- replay 방지
- HC-T-02: replay 탐지 시 enter_containment("HC-T-02") 호출
"""

import logging as _logging
import os
import sys
import threading
import time

_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

from mcp_containment_state import enter_containment

NONCE_TTL_SECONDS = 900


class NonceStore:
    """
    in-memory nonce 저장소.
    TTL 내 사용된 nonce를 추적하여 replay 방지.
    프로세스 재시작 시 초기화됨.
    replay 탐지 시 HC-T-02 -> HARD_CONTAINMENT 진입.
    """

    def __init__(self, ttl_seconds: int = NONCE_TTL_SECONDS):
        self._store: dict[str, float] = {}
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
        이미 사용된 경우: HC-T-02 -> HARD_CONTAINMENT 진입 후 False 반환.
        신규 nonce이면 등록 후 True 반환.
        """
        self._evict_expired()
        with self._lock:
            if nonce in self._store:
                # HC-T-02: replay attack 탐지
                _trigger_hct02()
                return False
            self._store[nonce] = time.time()
            return True

    def _evict_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [n for n, t in self._store.items() if now - t > self._ttl]
            for n in expired:
                del self._store[n]

    def size(self) -> int:
        self._evict_expired()
        with self._lock:
            return len(self._store)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


def _trigger_hct02() -> None:
    """HC-T-02: nonce replay -> HARD_CONTAINMENT 진입."""
    try:
        enter_containment("HC-T-02")
    except Exception as _rule6_e:
        _logging.debug("RULE6 mcp_nonce_store: %s", _rule6_e)


# 모듈 레벨 싱글턴
_nonce_store = NonceStore()


def is_nonce_used(nonce: str) -> bool:
    return _nonce_store.is_used(nonce)


def consume_nonce(nonce: str) -> bool:
    """nonce 소비. 성공(신규) = True / 실패(재사용) = False. 재사용 시 HC-T-02 발동."""
    return _nonce_store.mark_used(nonce)


def clear_nonce_store() -> None:
    """테스트 전용 초기화."""
    _nonce_store.clear()


def nonce_store_size() -> int:
    """테스트 전용 크기 조회."""
    return _nonce_store.size()
