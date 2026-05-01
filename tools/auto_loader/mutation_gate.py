from dataclasses import dataclass
from typing import Dict, Any
import time
import threading


ALLOWED_TARGETS = {
    "session_context.read",
    "auto_loader.load_result",
    "validation_runner.execute",
    "mutation_gate.evaluate",
}


@dataclass
class MutationRequest:
    target: str
    operation: str
    payload: Dict[str, Any]


@dataclass
class MutationResult:
    allowed: bool
    reason: str
    latency_ms: int


def evaluate(request: MutationRequest) -> MutationResult:
    start = time.time()
    result_holder = [None]
    timed_out = threading.Event()

    def _run():
        try:
            if not request.target or not request.operation:
                result_holder[0] = _deny("undefined target or operation", start)
                return

            if request.target not in ALLOWED_TARGETS:
                result_holder[0] = _deny("target not allowed", start)
                return

            if request.operation in {"write", "mutate", "overwrite", "bypass_gate", "direct_mutation"}:
                result_holder[0] = _deny("forbidden operation", start)
                return

            result_holder[0] = _allow("allowed", start)

        except Exception:
            result_holder[0] = _deny("exception occurred", start)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=0.05)

    if worker.is_alive():
        return MutationResult(allowed=False, reason="timeout occurred", latency_ms=50)

    return result_holder[0]


def _deny(reason: str, start: float) -> MutationResult:
    return MutationResult(
        allowed=False,
        reason=reason,
        latency_ms=int((time.time() - start) * 1000),
    )


def _allow(reason: str, start: float) -> MutationResult:
    return MutationResult(
        allowed=True,
        reason=reason,
        latency_ms=int((time.time() - start) * 1000),
    )
