ACTIVE_VERSION = "2.0.0"
VERSION_STATUS = "active"
import hashlib
import json
import os
import random
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .baseline_selector import BaselineSelectorError, select_baseline
from .delta_engine import DeltaEngineError, DeltaResult, compute_delta
from .hash_utils import compute_hash
from .state_events_normalizer import StateEventsNormalizerError, normalize_events
from .runtime_generator import load_runtime, compute_content_hash
from .boot_generator import generate as generate_boot
from .pair_validator import validate_boot_runtime_pair
from .boundary_enforcement_validator import validate_agent_boundaries

_GOVERNANCE_CONTEXT = {
    "policy_id": "ARSS_HUB_PROTOCOL_v1.2",
    "authority_root": "Beo",
    "jurisdiction": "AIBA_GLOBAL",
}

_DEFAULT_BUNDLE_MANIFEST = {
    "domi": ["SESSION_BOOT"],
    "jeni": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
    "caddy": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
    "normal_upload_bundle": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
}

ARSS_ROOT = Path("/opt/arss/engine/arss-protocol")
DEFAULT_RUNTIME_PATH = ARSS_ROOT / "SESSION_STATE_RUNTIME.json"


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
    boot_path: Optional[str] = None
    runtime_path: Optional[str] = None
    boot_hash: Optional[str] = None
    runtime_hash: Optional[str] = None
    runtime_pair_hash: Optional[str] = None
    validator_results: Optional[dict] = None


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
    material = (prev_chain_hash + ":" + payload_hash).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _build_receipt(
    prev_chain_hash: str,
    artifact_path: str,
    artifact_hash: str,
    prev_artifact_hash: str,
    boot_path: str = "",
    runtime_path: str = "",
    boot_hash: str = "",
    runtime_hash: str = "",
    runtime_pair_hash: str = "",
    validator_results: dict = None,
    commit_status: str = "PENDING",
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
            "chain": {"payload_hash": payload_hash, "prev_chain_hash": prev_chain_hash, "chain_hash": ch},
            "governance_context": _GOVERNANCE_CONTEXT,
        },
        "extension": {
            "artifact_path": artifact_path, "artifact_hash": artifact_hash,
            "prev_artifact_hash": prev_artifact_hash,
            "boot_path": boot_path, "runtime_path": runtime_path,
            "boot_hash": boot_hash, "runtime_hash": runtime_hash,
            "runtime_pair_hash": runtime_pair_hash,
            "validator_results": validator_results or {},
            "commit_status": commit_status, "extension_version": "2.0",
        },
    }


def run_pipeline(input_path: str, receipts_dir: str, output_dir: str, runtime_path: str = None, bundle_manifest: dict = None) -> PipelineResult:
    validator_results = {}
    stage = "1_load_input"
    if not os.path.exists(input_path):
        raise PipelineError(f"[{stage}] artifact not found: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        raw_content = f.read()
    try:
        input_data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise PipelineError(f"[{stage}] JSON parse failed: {e}")
    state_events = input_data.get("state_events", [])
    stage = "2_select_baseline"
    try:
        baseline = select_baseline(receipts_dir)
    except BaselineSelectorError as e:
        raise PipelineError(f"[{stage}] baseline not found: {e}")
    stage = "3_compute_artifact_hash"
    artifact_hash = compute_hash(raw_content)
    stage = "4_compute_delta"
    try:
        delta = compute_delta(baseline, input_path)
    except DeltaEngineError as e:
        raise PipelineError(f"[{stage}] {e}")
    stage = "5_normalize_state_events"
    try:
        normalized_events = normalize_events(state_events)
    except StateEventsNormalizerError as e:
        raise PipelineError(f"[{stage}] state_events normalization failure: {e}")
    stage = "6_validate_structure"
    if not isinstance(input_data, dict):
        raise PipelineError(f"[{stage}] schema mismatch")
    stage = "7_load_runtime_and_hash"
    rt_path = Path(runtime_path) if runtime_path else DEFAULT_RUNTIME_PATH
    try:
        runtime_data = load_runtime(rt_path)
        runtime_content_hash = compute_content_hash(runtime_data)
    except FileNotFoundError as e:
        raise PipelineError(f"[{stage}] RUNTIME load failed: {e}")
    except Exception as e:
        raise PipelineError(f"[{stage}] RUNTIME processing failed: {e}")
    stage = "8_generate_boot"
    os.makedirs(output_dir, exist_ok=True)
    boot_name = "SESSION_BOOT.json"
    boot_output_path = os.path.join(output_dir, boot_name)
    try:
        boot_data = generate_boot(full_path=input_path, boot_path=boot_output_path, runtime_pair_hash=runtime_content_hash)
    except Exception as e:
        raise PipelineError(f"[{stage}] boot generation failed: {e}")
    stage = "9_hash_boot"
    boot_hash = compute_hash(boot_data)
    stage = "10_pair_validator"
    boot_meta = boot_data.get("boot_meta", {})
    actual_runtime_pair_hash = boot_meta.get("runtime_pair_hash", "")
    pair_result = validate_boot_runtime_pair(boot_data, runtime_data)
    validator_results["pair_validator"] = pair_result
    if not pair_result["pass"]:
        raise PipelineError(f"[{stage}] pair_validator FAIL: {pair_result['errors']}")
    stage = "11_boundary_enforcement_validator"
    manifest = bundle_manifest if bundle_manifest is not None else _DEFAULT_BUNDLE_MANIFEST
    boundary_result = validate_agent_boundaries(manifest)
    validator_results["boundary_enforcement_validator"] = boundary_result
    if not boundary_result["pass"]:
        raise PipelineError(f"[{stage}] boundary_enforcement_validator FAIL: {boundary_result['errors']}")
    stage = "12_all_pass_gate"
    failed = [k for k, v in validator_results.items() if not v.get("pass", False)]
    if failed:
        raise PipelineError(f"[{stage}] ALL PASS gate FAIL: {failed}")
    stage = "13_generate_receipt"
    prev_chain_hash = baseline["candidate_rpu"]["chain"]["chain_hash"]
    prev_artifact_hash = baseline.get("extension", {}).get("artifact_hash", "")
    output_name = Path(input_path).name
    output_path = os.path.join(output_dir, output_name)
    output_data = dict(input_data)
    output_data["state_events"] = normalized_events
    output_data["_pipeline_meta"] = {"generated_at": _utc_ts(), "delta_status": delta.status, "pipeline_version": "session_context_gen/2.0", "runtime_first": True, "boot_path": boot_name, "runtime_path": str(rt_path)}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    receipt = _build_receipt(prev_chain_hash=prev_chain_hash, artifact_path=output_path, artifact_hash=artifact_hash, prev_artifact_hash=prev_artifact_hash, boot_path=boot_output_path, runtime_path=str(rt_path), boot_hash=boot_hash, runtime_hash=runtime_content_hash, runtime_pair_hash=actual_runtime_pair_hash, validator_results=validator_results, commit_status="READY_FOR_COMMIT")
    stage = "14_verify_and_promote"
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
    return PipelineResult(status="SUCCESS", delta=delta, receipt_path=receipt_path, output_path=output_path, stage=stage, boot_path=boot_output_path, runtime_path=str(rt_path), boot_hash=boot_hash, runtime_hash=runtime_content_hash, runtime_pair_hash=actual_runtime_pair_hash, validator_results=validator_results)
