"""
mcp_write_config.py — MCP Write Plane 공유 상수 모듈
PT-S136-MCP-WRITE-GATEKEEPER v1.0.0
"""

VPS_BASE = "/opt/arss/engine/arss-protocol"

REGISTRY_BASE = f"{VPS_BASE}/registry/mcp_write"
APPROVALS_DIR = f"{REGISTRY_BASE}/approvals"
AUDIT_DIR = f"{REGISTRY_BASE}/audit"
SNAPSHOTS_DIR = f"{REGISTRY_BASE}/snapshots"

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

TOKEN_TTL = 600  # 10분 (초)
HASH_ALGORITHM = "sha256"
