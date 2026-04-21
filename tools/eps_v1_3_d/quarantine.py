import os, shutil, json
from datetime import datetime

QUARANTINE = "/opt/arss/engine/arss-protocol/SNAPSHOT_LOG/quarantine/"

def quarantine_artifact(artifact_path):
    if not os.path.exists(artifact_path):
        return {"status": "SKIP", "reason": "artifact_not_found"}

    filename = os.path.basename(artifact_path)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = os.path.join(QUARANTINE, f"{timestamp}_{filename}")

    shutil.move(artifact_path, dest)
    os.chmod(dest, 0o400)

    log = {
        "quarantined_at_kst": datetime.now().isoformat(),
        "source_path": artifact_path,
        "dest_path": dest,
        "reason": "BINDING_GATE_FAIL"
    }
    log_path = dest + ".quarantine_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    os.chmod(log_path, 0o400)

    return {"status": "QUARANTINED", "dest": dest}
