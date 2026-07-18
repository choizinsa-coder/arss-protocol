"""
registry_lock_tool.py  (S428)
EAG-S428-LOCK-TOOL-IMPL-001

민감경로 잠금/해제/조회 도구. 비오님이 지목한 단일 경로 1건만 조작.
자동분류·일괄·자동잠금 없음. 살아있는 레지스트리는 검증된 사본으로만 원자 교체(락아웃 원차단).
정책코드(security_label_policy/mcp_read_server) 무변경. 이 도구는 레지스트리 파일 내용만 편집.
"""
import argparse
import json
import os
import sys
import time
import shutil
import fcntl
import tempfile
from pathlib import Path

MCP_DIR = "/opt/arss/engine/arss-protocol/tools/mcp"
if MCP_DIR not in sys.path:
    sys.path.insert(0, MCP_DIR)
import security_label_policy as slp

REGISTRY_PATH = Path(str(slp.REGISTRY_PATH))
LOCKDIR = REGISTRY_PATH.parent
AUDIT_LOG = Path(MCP_DIR) / "registry_lock_audit.log"
_LOCKABLE_LABELS = {"RESTRICTED", "SECRET"}


class LockToolError(Exception):
    pass


def _audit(action, path, label, result):
    try:
        line = json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "actor": "caddy", "action": action,
            "path": path, "label": label, "result": result,
        }, ensure_ascii=False)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _validate_file_as_registry(candidate_path):
    orig = slp.REGISTRY_PATH
    try:
        slp.REGISTRY_PATH = Path(candidate_path)
        return slp._load_registry()
    finally:
        slp.REGISTRY_PATH = orig


def _read_current():
    _validate_file_as_registry(str(REGISTRY_PATH))
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("labels"), list):
        raise LockToolError("REGISTRY_SCHEMA_UNEXPECTED")
    return data


def _backup():
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        shutil.copy2(str(REGISTRY_PATH), str(REGISTRY_PATH) + ".bak." + ts)
    except Exception:
        pass


def _atomic_write_validated(data):
    LOCKDIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".registry.", suffix=".tmp", dir=str(LOCKDIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _validate_file_as_registry(tmp)  # 생산 검증기로 tmp 검증 (I2/I3)
        try:
            st = REGISTRY_PATH.stat()
            os.chmod(tmp, st.st_mode & 0o777)
        except Exception:
            pass
        os.replace(tmp, str(REGISTRY_PATH))  # 동일 FS 원자 교체 (I1/I4)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass


def _with_lock(fn):
    LOCKDIR.mkdir(parents=True, exist_ok=True)
    lock_file = LOCKDIR / ".registry_edit.lock"
    with open(lock_file, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def lock_path(target_path, label, force=False):
    if label not in _LOCKABLE_LABELS:
        raise LockToolError("LABEL_MUST_BE_RESTRICTED_OR_SECRET")
    rp = str(Path(target_path).resolve())
    def _do():
        data = _read_current()
        labels = data["labels"]
        existing = next((e for e in labels if str(Path(e["path"]).resolve()) == rp), None)
        if existing is not None and not force:
            raise LockToolError("ALREADY_REGISTERED:%s" % existing.get("label"))
        _backup()
        if existing is not None:
            existing["label"] = label
        else:
            labels.append({"path": rp, "label": label})
        _atomic_write_validated(data)
        return rp
    try:
        _with_lock(_do)
        _audit("lock", rp, label, "OK")
        return {"ok": True, "path": rp, "label": label}
    except Exception as e:
        _audit("lock", rp, label, "FAIL:%s" % e)
        raise


def unlock_path(target_path):
    rp = str(Path(target_path).resolve())
    def _do():
        data = _read_current()
        labels = data["labels"]
        before = len(labels)
        newlabels = [e for e in labels if str(Path(e["path"]).resolve()) != rp]
        if len(newlabels) == before:
            return {"ok": True, "path": rp, "removed": False, "note": "NOT_REGISTERED_NOOP"}
        _backup()
        data["labels"] = newlabels
        _atomic_write_validated(data)
        return {"ok": True, "path": rp, "removed": True}
    try:
        out = _with_lock(_do)
        _audit("unlock", rp, "", "OK:%s" % out.get("removed"))
        return out
    except Exception as e:
        _audit("unlock", rp, "", "FAIL:%s" % e)
        raise


def list_locks():
    data = _read_current()
    return {"ok": True, "entries": [{"path": e["path"], "label": e["label"]} for e in data["labels"]]}


def main():
    ap = argparse.ArgumentParser(description="registry lock tool (single path only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("lock")
    pl.add_argument("path")
    pl.add_argument("--label", required=True, choices=["RESTRICTED", "SECRET"])
    pl.add_argument("--force", action="store_true")
    pu = sub.add_parser("unlock")
    pu.add_argument("path")
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "lock":
        print(json.dumps(lock_path(args.path, args.label, args.force), ensure_ascii=False))
    elif args.cmd == "unlock":
        print(json.dumps(unlock_path(args.path), ensure_ascii=False))
    elif args.cmd == "list":
        print(json.dumps(list_locks(), ensure_ascii=False))


if __name__ == "__main__":
    main()
