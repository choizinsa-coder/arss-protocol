import sys, os
from pathlib import Path
sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools")
import observation_server as obs
obs.register_token("domi", "domi-test-token-s142", ttl_seconds=3600)
obs.register_token("jeni", "jeni-test-token-s142", ttl_seconds=3600)
print("[SETUP] tokens registered")
from projection_builder import get_projection
from sandbox_validator import validate_write, check_safe_pass_batch, SANDBOX_ROOT
proj, is_stale = get_projection()
auth = proj.get("AUTHORITY_LEVEL")
exe = proj.get("execution_allowed")
print(f"[PROJ] stale={is_stale} execution_allowed={exe} AUTHORITY={auth}")
file_name = "task-S142-E2E-domi-design.md"
target = str(SANDBOX_ROOT / "domi" / "active" / "proposals" / file_name)
Path(target).parent.mkdir(parents=True, exist_ok=True)
r1 = validate_write("domi", target, b"content", file_name, "DRAFT")
print(f"[1] domi write: allowed={r1.allowed} reason={r1.reason}")
assert r1.allowed, r1.reason
with open(target, "w") as f:
    f.write("content")
assert Path(target).exists()
print("[2] file exists: True")
r2 = validate_write("jeni", target, b"overwrite", file_name, "DRAFT")
print(f"[3] jeni overwrite: allowed={r2.allowed} reason={r2.reason}")
assert not r2.allowed and "CROSS_OVERWRITE" in r2.reason, f"FAIL: {r2.reason}"
r3 = check_safe_pass_batch("domi", [target], ["BEO_PENDING"])
print(f"[4] safe_pass BEO_PENDING: allowed={r3.allowed} reason={r3.reason}")
assert not r3.allowed, "FAIL: BEO_PENDING should be denied"
os.remove(target)
print("[CLEANUP] test file removed")
print("ALL PASS")
