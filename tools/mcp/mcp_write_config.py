"""
mcp_write_config.py — MCP Write Plane 공유 상수 모듈 v1.1.0
PT-S136-MCP-WRITE-GATEKEEPER

v1.1.0: RECEIPTS_DIR / BASELINES_DIR / INTAKE_DIR / SOFT_TOKEN_TTL 추가
"""

VPS_BASE = "/opt/arss/engine/arss-protocol"

REGISTRY_BASE = f"{VPS_BASE}/registry/mcp_write"
APPROVALS_DIR = f"{REGISTRY_BASE}/approvals"
AUDIT_DIR = f"{REGISTRY_BASE}/audit"
SNAPSHOTS_DIR = f"{REGISTRY_BASE}/snapshots"
RECEIPTS_DIR = f"{REGISTRY_BASE}/receipts"
BASELINES_DIR = f"{REGISTRY_BASE}/baselines"
INTAKE_DIR = f"{REGISTRY_BASE}/intake"

ALLOWED_SANDBOX_PATHS = [
    f"{VPS_BASE}/tools/sandbox/",
    f"{VPS_BASE}/tools/tmp/",
    f"{VPS_BASE}/tests/sandbox/",
]

FORBIDDEN_PATH_PREFIXES = [
    f"{VPS_BASE}/registry/",
    f"{VPS_BASE}/tools/session_context_gen/",
    f"{VPS_BASE}/tools/governance/",
    f"{VPS_BASE}/SESSION_CONTEXT",
    f"{VPS_BASE}/chain",
    f"{VPS_BASE}/boot",
    f"{VPS_BASE}/evidence",
    f"{VPS_BASE}/SNAPSHOT_LOG",
    f"{VPS_BASE}/sync_metadata",
]

ALLOWED_EXTENSIONS = {".md", ".json", ".txt"}
FORBIDDEN_EXTENSIONS = {".py", ".sh", ".env", ".yaml", ".yml", ".service"}

TOKEN_TTL = 600       # 10분 HARD limit
SOFT_TOKEN_TTL = 480  # 8분 SOFT limit (초과 시 FC-T1)
HASH_ALGORITHM = "sha256"
