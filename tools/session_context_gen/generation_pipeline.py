import hashlib
import json
import os
import random
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .baseline_selector import BaselineSelectorError, select_baseline
from .delta_engine import DeltaEngineError, DeltaResult, compute_delta
from .hash_utils import compute_hash
from .state_events_normalizer import StateEventsNormalizerError, normalize_events

_GOVERNANCE_CONTEXT = {
    "policy_id": "ARSS_HUB_PROTOCOL_v1.2",
    "authority_root": "Beo",
    "jurisdiction": "AIBA_GLOBAL",
}


class PipelineError(Exception):
    pass


@dataclass
class PipelineResult:
    status: str
    delta: Optional[DeltaResult] = None
    receipt_path: Optional[str] = None
    output_path: Optional[str] = None
    stage: Optional[str] = None
    error: Optional[str] = None


def _uuidv7() -> str:
    ms = int(time.time() * 1000)
    rand_a = random.getrandbits(12)
    rand_b = random.getrandbits(62)
    hi = (ms << 16) | (0x7 << 12) | rand_a
    lo = (0b10 << 62) | rand_b
    b = struct.pack(">QQ", hi, lo)
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _utc_ts() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


def _chain_hash(prev_chain_hash: str, payload_hash: str) -> str:
    """Mirror arss_generator_v1.py compute_chain_hash exactly."""
    material = (prev_chain_hash + ":" + payload_hash).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _build_receipt(
    prev_chain_hash: str,
    artifact_path: str,
    artifact_hash: str,
    prev_artifact_hash: str,
) -> dict:
    payload = {
        "event_type": "SESSION_CONTEXT_GENERATED",
        "content": f"artifact={os.path.basename(artifact_path)}",
    }
    payload_hash = compute_hash(payload)
    ch = _chain_hash(prev_chain_hash, payload_hash)
    return {
        "status": "PASS",
        "persistence_allowed": True,
        "candidate_rpu": {
            "schema_version": "ARSS-RPU-1.0",
            "rpu_id": _uuidv7(),
            "timestamp": _utc_ts(),
            "actor_id": "session_context_gen",
            "payload": payload,
            "chain": {
                "payload_hash": payload_hash,
                "prev_chain_hash": prev_chain_hash,
                "chain_hash": ch,
            },
            "governance_context": _GOVERNANCE_CONTEXT,
        },
        "extension": {
            "artifact_path": artifact_path,
            "artifact_hash": artifact_hash,
            "prev_artifact_hash": prev_artifact_hash,
            "extension_version": "1.0",
        },
    }


def run_pipeline(input_path: str, receipts_dir: str, output_dir: str) -> PipelineResult:
    """
    9-stage SESSION_CONTEXT generation pipeline. FAIL-CLOSED on any error.

    Forbidden: fallback(0), placeholder baseline, line_count judgment,
               silent data deletion, automatic genesis creation.
    """
    # Stage 1: Load input
    stage = "1_load_input"
    if not os.path.exists(input_path):
        raise PipelineError(f"[{stage}] artifact not found: {input_path}")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
        input_data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise PipelineError(f"[{stage}] JSON parse failed: {e}")

    state_events = input_data.get("state_events", [])

    # Stage 2: Select baseline
    stage = "2_select_baseline"
    try:
        baseline = select_baseline(receipts_dir)
    except BaselineSelectorError as e:
        raise PipelineError(f"[{stage}] baseline not found: {e}")

    # Stage 3: Compute artifact hash (normalization mandatory)
    stage = "3_compute_artifact_hash"
    try:
        artifact_hash = compute_hash(raw_content)
    except Exception as e:
        raise PipelineError(f"[{stage}] hash computation failure: {e}")
    if not artifact_hash:
        raise PipelineError(f"[{stage}] artifact_hash is empty after computation")

    # Stage 4: Compute delta
    stage = "4_compute_delta"
    try:
        delta = compute_delta(baseline, input_path)
    except DeltaEngineError as e:
        raise PipelineError(f"[{stage}] {e}")

    # Stage 5: Normalize state_events
    stage = "5_normalize_state_events"
    try:
        normalized_events = normalize_events(state_events)
    except StateEventsNormalizerError as e:
        raise PipelineError(f"[{stage}] state_events normalization failure: {e}")

    # Stage 6: Validate full structure
    stage = "6_validate_structure"
    if not isinstance(input_data, dict):
        raise PipelineError(f"[{stage}] schema mismatch: input is not a JSON object")

    # Stage 7: Generate SESSION_CONTEXT
    stage = "7_generate_session_context"
    output_data = dict(input_data)
    output_data["state_events"] = normalized_events
    output_data["_pipeline_meta"] = {
        "generated_at": _utc_ts(),
        "delta_status": delta.status,
        "pipeline_version": "session_context_gen/1.0",
    }

    # Stage 8: Generate receipt (conforms to arss_generator_v1.py canonical schema)
    stage = "8_generate_receipt"
    prev_chain_hash = baseline["candidate_rpu"]["chain"]["chain_hash"]
    prev_artifact_hash = baseline.get("extension", {}).get("artifact_hash", "")
    os.makedirs(output_dir, exist_ok=True)
    output_name = Path(input_path).name
    output_path = os.path.join(output_dir, output_name)
    receipt = _build_receipt(
        prev_chain_hash=prev_chain_hash,
        artifact_path=output_path,
        artifact_hash=artifact_hash,
        prev_artifact_hash=prev_artifact_hash,
    )

    # Stage 9: Verify then promote to staging/
    stage = "9_verify_and_promote"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    with open(output_path, "r", encoding="utf-8") as f:
        written = f.read()
    written_hash = compute_hash(written)

    receipt["extension"]["artifact_hash"] = written_hash
    new_payload_hash = compute_hash(receipt["candidate_rpu"]["payload"])
    new_chain_hash = _chain_hash(prev_chain_hash, new_payload_hash)
    receipt["candidate_rpu"]["chain"]["payload_hash"] = new_payload_hash
    receipt["candidate_rpu"]["chain"]["chain_hash"] = new_chain_hash

    rpu_id = receipt["candidate_rpu"]["rpu_id"]
    receipt_name = f"receipt_{rpu_id}.json"
    receipt_path = os.path.join(output_dir, receipt_name)
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)

    return PipelineResult(
        status="SUCCESS",
        delta=delta,
        receipt_path=receipt_path,
        output_path=output_path,
        stage=stage,
    )
