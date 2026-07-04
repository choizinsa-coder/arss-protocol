#!/usr/bin/env python3
"""
step7_boot_briefing.py
SESSION BOOT Step 7 — Always-On Phase 1
EAG: EAG-S326-STEP7-001

역할: SESSION BOOT Step 6 완료 후 캐디가 run_script로 실행.
      boot_briefing.json을 읽어 비오님용 3줄 이내 브리핑 생성.
      결과를 step7_result.json에 저장 (캐디 read_file 확인용).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT         = Path("/opt/arss/engine/arss-protocol")
MONITOR_DIR  = ROOT / "tools/monitor"
BRIEFING_SRC = MONITOR_DIR / "boot_briefing.json"
RESULT_PATH  = MONITOR_DIR / "step7_result.json"


def build_briefing(data: dict) -> list:
    lines = []
    ghs    = data.get("ghs", {})
    status = ghs.get("status", "UNKNOWN")
    score  = round(float(ghs.get("score", 0.0)), 1)
    lines.append("GHS: {} {}".format(status, score))
    tc = data.get("triggers_fired_count", 0)
    if tc and tc > 0:
        fired = data.get("triggers_fired", [])
        lines.append("Trigger: {}건 — {}".format(tc, ", ".join(str(t) for t in fired)))
    overdue = data.get("overdue_reviews", [])
    if overdue:
        lines.append("Overdue Review: {}건 — {}".format(
            len(overdue), ", ".join(str(r) for r in overdue)
        ))
    return lines if lines else ["모니터 데이터 없음"]


def main():
    generated_at = datetime.now(timezone.utc).isoformat()
    if not BRIEFING_SRC.exists():
        result = {
            "step": 7,
            "source": "step7_boot_briefing.py",
            "generated_at": generated_at,
            "briefing_lines": ["모니터 데이터 없음"],
            "summary": "FAIL_OPEN: boot_briefing.json not found",
        }
    else:
        try:
            with open(BRIEFING_SRC, encoding="utf-8") as f:
                data = json.load(f)
            lines = build_briefing(data)
            result = {
                "step": 7,
                "source": "step7_boot_briefing.py",
                "generated_at": generated_at,
                "briefing_source_at": data.get("generated_at", ""),
                "briefing_lines": lines,
                "summary": " | ".join(lines),
            }
        except Exception as e:
            result = {
                "step": 7,
                "source": "step7_boot_briefing.py",
                "generated_at": generated_at,
                "briefing_lines": ["모니터 데이터 없음"],
                "summary": "FAIL_OPEN: {}".format(str(e)),
            }
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    for line in result["briefing_lines"]:
        print(line)
    sys.exit(0)


if __name__ == "__main__":
    main()
