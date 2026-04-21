import os
import json
from datetime import datetime

STAGING = "/opt/arss/engine/arss-protocol/staging/"
INCOMPLETE_CLOSE_FLAG = os.path.join(STAGING, ".incomplete_close")


def detect_incomplete_close() -> dict:
    if os.path.exists(INCOMPLETE_CLOSE_FLAG):
        try:
            with open(INCOMPLETE_CLOSE_FLAG, "r") as f:
                data = json.load(f)
        except Exception:
            data = {"job_id": "UNKNOWN", "reason": "FLAG_FILE_UNREADABLE"}
        return {
            "incomplete": True,
            "job_id": data.get("job_id", "UNKNOWN"),
            "reason": data.get("reason", ""),
            "marked_at": data.get("marked_at", ""),
        }
    return {"incomplete": False, "job_id": None, "reason": ""}


def mark_incomplete_close(job_id: str, reason: str) -> None:
    os.makedirs(STAGING, exist_ok=True)
    data = {
        "job_id": job_id,
        "reason": reason,
        "marked_at": datetime.now().isoformat(),
    }
    with open(INCOMPLETE_CLOSE_FLAG, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clear_incomplete_close() -> None:
    if os.path.exists(INCOMPLETE_CLOSE_FLAG):
        os.remove(INCOMPLETE_CLOSE_FLAG)
