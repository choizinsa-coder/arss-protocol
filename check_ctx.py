import json

with open("SESSION_CONTEXT.json", encoding="utf-8") as f:
    ctx = json.load(f)

print("session_count:", ctx.get("session_count"))
print("ssoi_status present:", "ssoi_status" in ctx)
print("total keys:", len(ctx.keys()))
print("all keys:", sorted(ctx.keys()))
