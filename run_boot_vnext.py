import json
from tools.session_context_gen.boot_vnext_generator import generate

with open("SESSION_CONTEXT.json", encoding="utf-8") as f:
    ctx = json.load(f)

result = generate(
    ctx,
    runtime_pair_hash="dccec82e2b4e2a868a2688d0955d1d842610e70e95b03aa4a04e9cb41ef18e80"
)

print(json.dumps(result, ensure_ascii=False, indent=2))

# PASS 시 파일 저장
if result.get("status") in ("PASS", "REVIEW"):
    boot = result["boot"]
    out_path = "SESSION_BOOT_S123_vNext.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(boot, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVED] {out_path}")
