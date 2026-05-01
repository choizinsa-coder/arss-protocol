"""
EPS v1.4 Wrapper — Final External Emission Gate.

Insertion point: final external emission boundary only.
  - agent final response emission
  - document/report finalization before save/show
  - n8n external send node just before outbound send

NOT for:
  - rpu_atomic_issuer.py internal path
  - verifier core
  - status server internal validation
  - chain calculation path
"""
from .segmenter import bind_proposed_blocks, segment_statements
from .enforcement import enforce_statement

def _blocked(reason_code: str, segment_results: list | None = None) -> dict:
    return {
        "status": "BLOCKED",
        "formatted_output": None,
        "reason_code": reason_code,
        "segment_results": segment_results or [],
    }

def _passed(formatted_output: str, segment_results: list) -> dict:
    return {
        "status": "PASS",
        "formatted_output": formatted_output,
        "reason_code": None,
        "segment_results": segment_results,
    }

def _join_segments(segment_results: list) -> str:
    return "\n".join(
        r.formatted_output for r in segment_results
        if r.formatted_output is not None
    )

def wrapper_execute(payload: dict) -> dict:
    """
    Full-buffer validation.
    One blocked segment blocks all.
    No partial emission.
    """
    try:
        raw_output = payload.get("raw_output", "")
        context = payload.get("context", {})

        if not raw_output or not raw_output.strip():
            return _blocked("EMPTY_OUTPUT")

        bound_blocks = bind_proposed_blocks(raw_output)
        segments = segment_statements(bound_blocks)

        if not segments:
            return _blocked("EMPTY_OUTPUT")

        segment_results = []
        for segment in segments:
            r = enforce_statement(segment, context)
            segment_results.append(r)
            if r.status != "PASS":
                return _blocked(
                    r.reason if r.reason else "SEGMENT_BLOCKED",
                    segment_results=segment_results,
                )

        final_output = _join_segments(segment_results)
        return _passed(final_output, segment_results)

    except Exception as e:
        return _blocked(f"UNEXPECTED_EXCEPTION: {e}")


def safe_emit_wrapper_result(result: dict) -> str | None:
    """
    Outer leak prevention contract.
    MUST be the only emission path after wrapper_execute().
    NEVER fallback to raw output on BLOCKED or error.
    """
    if result.get("status") == "PASS" and result.get("formatted_output") is not None:
        return result["formatted_output"]
    return None
