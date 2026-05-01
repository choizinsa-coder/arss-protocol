from dataclasses import dataclass
from typing import Optional

from .field_contract import Verdict


@dataclass(frozen=True)
class LoadResult:
    target_id: str
    source_resolved: bool
    loaded: bool
    hash: Optional[str]
    verdict: Verdict
    failure_reason: Optional[str] = None
    apply_allowed: bool = False
    next_allowed: bool = False


def make_load_result(
    target_id: str,
    source_resolved: bool,
    loaded: bool,
    content_hash: Optional[str],
    failure_reason: Optional[str],
) -> LoadResult:
    if failure_reason:
        return LoadResult(
            target_id=target_id,
            source_resolved=source_resolved,
            loaded=loaded,
            hash=content_hash,
            verdict=Verdict.FAIL,
            failure_reason=failure_reason,
            apply_allowed=False,
            next_allowed=False,
        )
    return LoadResult(
        target_id=target_id,
        source_resolved=source_resolved,
        loaded=loaded,
        hash=content_hash,
        verdict=Verdict.PASS,
        failure_reason=None,
        apply_allowed=True,
        next_allowed=True,
    )
