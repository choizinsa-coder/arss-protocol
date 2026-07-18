"""
sensitive_candidate_scanner.py
S428 — 기존 민감파일 후보 스캐너 (독립 실행, 읽기전용)
EAG-S428-SENSITIVE-CANDIDATE-IMPL-001

- CODE_ROOT 이하를 읽기전용 스캔 → 후보 목록(JSON) 출력.
- 등록/잠금 없음. SECURITY_LABEL_REGISTRY / Layer2 모듈 미접촉 (I1/I10).
- 비오님이 출력을 보고 수동으로만 등록.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sensitive_candidate_heuristic as heur

CODE_ROOT = "/opt/arss/engine/arss-protocol"


def main():
    out_path = os.environ.get("SCAN_OUT") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "sensitive_candidates.json")
    scan_root = os.environ.get("SCAN_ROOT", CODE_ROOT)
    candidates = heur.scan_tree(scan_root)
    payload = {
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "scan_root": scan_root,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("[scanner] candidates=%d out=%s" % (len(candidates), out_path))


if __name__ == "__main__":
    main()
