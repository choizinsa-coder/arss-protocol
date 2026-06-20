"""
transaction_registry.py
영역 8 — Transaction Registry (Replay Attack 방지)
EAG-S271-DIRECTCH-001

제니 TRUST-ADVISORY ② 반영:
  tx_id 는 세션 고유 난수(uuid4). 과거 세션의 정당한 서명을 가로채
  현재 chain.tip 에 재주입하는 Replay 공격을 실시간 블로킹으로 차단.

register() 는 최초 등록만 허용. 중복 tx_id 는 즉시 REPLAY_DETECTED.
"""

from __future__ import annotations

import json
import os


class TransactionRegistry:
    """본 tx_id 1회성 보장. 인메모리 set + 영속 백업."""

    def __init__(self, persist_path: str | None = None):
        self._seen: set[str] = set()
        self._persist_path = persist_path
        if persist_path and os.path.isfile(persist_path):
            self._load(persist_path)

    def _load(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for tid in data.get("seen", []):
                self._seen.add(tid)
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def is_seen(self, tx_id: str) -> bool:
        return tx_id in self._seen

    def register(self, tx_id: str) -> bool:
        """
        최초 등록 시 True, 중복(replay) 시 False.
        실시간 블로킹 — 검사와 등록을 원자적으로 수행.
        """
        if tx_id in self._seen:
            return False
        self._seen.add(tx_id)
        self._persist()
        return True

    def count(self) -> int:
        return len(self._seen)

    def _persist(self) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump({"seen": sorted(self._seen)}, f, ensure_ascii=False)
        except OSError:
            pass
