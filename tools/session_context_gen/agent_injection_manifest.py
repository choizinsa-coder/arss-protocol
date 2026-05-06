"""
agent_injection_manifest.py
PT-S81-ARCH-001 Phase 2 Step 9

Purpose:
- 에이전트별 주입 범위 manifest 생성

Required manifest:
{
  "domi": ["SESSION_BOOT"],
  "jeni": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
  "caddy": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
  "normal_upload_bundle": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"]
}

Rule:
- FULL excluded from normal bundle
- Domi = BOOT only
- Jeni = BOOT + RUNTIME
- Caddy = BOOT + RUNTIME
"""

MANIFEST_SPEC = {
    "domi": ["SESSION_BOOT"],
    "jeni": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
    "caddy": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
    "normal_upload_bundle": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
}

FORBIDDEN_IN_NORMAL = "SESSION_CONTEXT_FULL"


def generate_manifest() -> dict:
    """
    Returns the canonical agent injection manifest.
    """
    return {k: list(v) for k, v in MANIFEST_SPEC.items()}


def validate_manifest(manifest: dict) -> dict:
    """
    Args:
        manifest: dict to validate against MANIFEST_SPEC

    Returns:
        {
            "pass": bool,
            "validator": "agent_injection_manifest",
            "errors": [str],
            "manifest": dict,
        }
    """
    errors = []

    # 전체 에이전트 키 존재 확인
    for agent, expected_zones in MANIFEST_SPEC.items():
        if agent not in manifest:
            errors.append(f"FAIL: agent key missing — {agent}")
            continue

        actual_zones = set(manifest[agent])
        expected_set = set(expected_zones)

        missing = sorted(expected_set - actual_zones)
        extra = sorted(actual_zones - expected_set)

        if missing:
            errors.append(f"FAIL: {agent} missing zones — {missing}")
        if extra:
            errors.append(f"FAIL: {agent} has unexpected zones — {extra}")

    # FULL 금지 검사 (모든 에이전트)
    for agent, zones in manifest.items():
        if FORBIDDEN_IN_NORMAL in zones:
            errors.append(
                f"FAIL: {FORBIDDEN_IN_NORMAL} found in {agent} injection scope"
            )

    # Domi = BOOT only 강제
    if "domi" in manifest:
        domi_zones = set(manifest["domi"])
        if domi_zones != {"SESSION_BOOT"}:
            errors.append(
                f"FAIL: domi must have SESSION_BOOT only, got {sorted(domi_zones)}"
            )

    passed = len(errors) == 0

    return {
        "pass": passed,
        "validator": "agent_injection_manifest",
        "errors": errors,
        "manifest": manifest,
    }
