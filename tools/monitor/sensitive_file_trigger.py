"""
sensitive_file_trigger.py  (S428)
EAG-S428-SENSITIVE-CANDIDATE-IMPL-001

신규/변경 민감파일 후보 감지 로직 (aiba_monitor가 위임 호출).
원칙: 제안 전용. 등급·등록·잠금 없음. 본문·시크릿 미저장 (경로 + reason_code만).
seen-state는 path->reason_code 서명만 저장 (등급 필드 없음). 배포 시 seed된 기존 파일은 신규 아님.
"""
import os
import sys
import json
from collections import Counter


def _sig(c):
    return ",".join(c.get("reason_codes", []))


def check_sensitive_file_trigger(timestamp_iso, root, monitor_dir):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sensitive_candidate_heuristic as heur
        seen_path = os.path.join(str(monitor_dir), "sensitive_seen_state.json")
        cand_path = os.path.join(str(monitor_dir), "sensitive_candidates.json")
        candidates = heur.scan_tree(str(root))
        with open(cand_path, "w", encoding="utf-8") as f:
            json.dump({"scanned_at": timestamp_iso, "scan_root": str(root),
                       "candidate_count": len(candidates), "candidates": candidates},
                      f, ensure_ascii=False, indent=2)
        seen = {}
        if os.path.exists(seen_path):
            try:
                with open(seen_path, encoding="utf-8") as f:
                    seen = json.load(f)
            except Exception:
                seen = {}
        new_items = [c for c in candidates if seen.get(c["path"]) != _sig(c)]
        new_seen = {c["path"]: _sig(c) for c in candidates}
        try:
            with open(seen_path, "w", encoding="utf-8") as f:
                json.dump(new_seen, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        fired = bool(new_items)
        detail = ""
        if fired:
            rc = Counter()
            for c in new_items:
                for code in c.get("reason_codes", []):
                    rc[code] += 1
            agg = " ".join("%s x%d" % (k, v) for k, v in sorted(rc.items()))
            detail = "신규 민감 후보 %d건 (%s). 목록: tools/monitor/sensitive_candidates.json" % (len(new_items), agg)
        return {"trigger": "Sensitive_File", "fired": fired, "detail": detail,
                "cause_type": "sensitive_file" if fired else "",
                "cause_component": "scanner", "cause_rc": "NEW",
                "cause_count": len(new_items)}
    except Exception as e:
        return {"trigger": "Sensitive_File", "fired": False,
                "detail": "sensitive_probe_error: %s" % e}
