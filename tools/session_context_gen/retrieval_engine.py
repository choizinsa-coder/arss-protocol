"""
retrieval_engine.py — SESSION_CONTEXT Section Retrieval Engine
PT-S56-001 | AIBA Global Project
"""

import json
import time
from pathlib import Path
from typing import Any, Optional
from tools.session_context_gen.hash_utils import compute_hash

# ── 상수 ──────────────────────────────────────────────────────────────────────
DEFAULT_TOKEN_BUDGET = 4000          # 기본 토큰 예산 (섹션당)
CACHE_TTL_SECONDS    = 300           # 캐시 유효 시간 (5분)

# section whitelist — full_context_manager와 동기화 필수
ALLOWED_SECTIONS = {
    "chain",
    "canonical_rules",
    "session_reentry",
    "agent_focus",
    "pending_tasks",
    "decisions",
    "automation_roadmap",
    "sync_metadata",
    "scp_standard_path",
    "wf_structure_confirmed",
}

# ── Budget Tracker ─────────────────────────────────────────────────────────────
class BudgetTracker:
    def __init__(self, total: int = DEFAULT_TOKEN_BUDGET):
        self._total     = total
        self._remaining = total
        self._log: list[dict] = []

    def consume(self, section: str, estimated_tokens: int) -> bool:
        """소비 시도. 예산 초과 시 False(FAIL-CLOSED) 반환."""
        if estimated_tokens > self._remaining:
            self._log.append({
                "section": section,
                "requested": estimated_tokens,
                "remaining": self._remaining,
                "result": "REJECTED"
            })
            return False
        self._remaining -= estimated_tokens
        self._log.append({
            "section": section,
            "requested": estimated_tokens,
            "remaining": self._remaining,
            "result": "ACCEPTED"
        })
        return True

    def remaining(self) -> int:
        return self._remaining

    def report(self) -> dict:
        return {
            "total": self._total,
            "remaining": self._remaining,
            "consumed": self._total - self._remaining,
            "log": self._log,
        }


# ── Aggregation Tracker ────────────────────────────────────────────────────────
class AggregationTracker:
    def __init__(self):
        self._sections: list[str]  = []
        self._results:  dict       = {}
        self._errors:   list[dict] = []

    def record(self, section: str, data: Any, error: Optional[str] = None):
        self._sections.append(section)
        if error:
            self._errors.append({"section": section, "error": error})
            self._results[section] = None
        else:
            self._results[section] = data

    def get_result(self, section: str) -> Any:
        return self._results.get(section)

    def summary(self) -> dict:
        return {
            "sections_requested": self._sections,
            "sections_ok":   [s for s in self._sections if s not in {e["section"] for e in self._errors}],
            "sections_error": self._errors,
        }


# ── Session Cache ──────────────────────────────────────────────────────────────
class SessionCache:
    def __init__(self, ttl: int = CACHE_TTL_SECONDS):
        self._ttl   = ttl
        self._store: dict[str, dict] = {}   # key → {value, expires_at, hash}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            del self._store[key]
            return None
        return entry["value"]

    def set(self, key: str, value: Any):
        self._store[key] = {
            "value":      value,
            "expires_at": time.time() + self._ttl,
            "hash":       compute_hash(value) if isinstance(value, (dict, list)) else None,
        }

    def invalidate(self, key: str):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()

    def stats(self) -> dict:
        now = time.time()
        return {
            "total_keys": len(self._store),
            "active_keys": sum(1 for e in self._store.values() if e["expires_at"] > now),
        }


# ── Retrieval Engine ───────────────────────────────────────────────────────────
class RetrievalEngine:
    """
    5단계 Integration Flow:
      1. 캐시 조회 (hit → 즉시 반환)
      2. 섹션 whitelist 검증
      3. 예산 체크 (FAIL-CLOSED)
      4. full_context에서 섹션 로드
      5. 캐시 저장 후 반환
    """

    def __init__(self, full_ctx_path: Path, budget: Optional[int] = None):
        self._ctx_path = full_ctx_path
        self._cache    = SessionCache()
        self._budget   = BudgetTracker(budget or DEFAULT_TOKEN_BUDGET)
        self._agg      = AggregationTracker()
        self._ctx: Optional[dict] = None   # lazy-load

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────────────
    def _load_ctx(self) -> dict:
        if self._ctx is None:
            with open(self._ctx_path, encoding="utf-8") as f:
                self._ctx = json.load(f)
        return self._ctx

    @staticmethod
    def _estimate_tokens(data: Any) -> int:
        """대략적 토큰 추정 (JSON 직렬화 문자 수 / 4)."""
        try:
            s = json.dumps(data, ensure_ascii=False)
        except Exception:
            s = str(data)
        return max(1, len(s) // 4)

    # ── 공개 API ───────────────────────────────────────────────────────────────
    def get_section(self, section: str) -> dict:
        """
        단일 섹션 조회. 반환 형식:
          {"ok": True,  "section": str, "data": Any}
          {"ok": False, "section": str, "error": str}
        """
        # STEP 1 — 캐시 조회
        cached = self._cache.get(section)
        if cached is not None:
            self._agg.record(section, cached)
            return {"ok": True, "section": section, "data": cached, "source": "cache"}

        # STEP 2 — whitelist 검증
        if section not in ALLOWED_SECTIONS:
            err = f"SECTION_NOT_ALLOWED: {section}"
            self._agg.record(section, None, error=err)
            return {"ok": False, "section": section, "error": err}

        # STEP 3 — 예산 체크 (사전 추정)
        ctx  = self._load_ctx()
        data = ctx.get(section)
        if data is None:
            err = f"SECTION_NOT_FOUND: {section}"
            self._agg.record(section, None, error=err)
            return {"ok": False, "section": section, "error": err}

        estimated = self._estimate_tokens(data)
        if not self._budget.consume(section, estimated):
            err = f"BUDGET_EXCEEDED: {section} needs ~{estimated} tokens, remaining={self._budget.remaining()}"
            self._agg.record(section, None, error=err)
            return {"ok": False, "section": section, "error": err}

        # STEP 4 & 5 — 캐시 저장 후 반환
        self._cache.set(section, data)
        self._agg.record(section, data)
        return {"ok": True, "section": section, "data": data, "source": "ctx"}

    def get_sections(self, sections: list[str]) -> dict:
        """다중 섹션 일괄 조회."""
        results = {}
        for s in sections:
            results[s] = self.get_section(s)
        return results

    def budget_report(self) -> dict:
        return self._budget.report()

    def aggregation_summary(self) -> dict:
        return self._agg.summary()

    def cache_stats(self) -> dict:
        return self._cache.stats()

    def invalidate_cache(self, section: Optional[str] = None):
        if section:
            self._cache.invalidate(section)
        else:
            self._cache.clear()
