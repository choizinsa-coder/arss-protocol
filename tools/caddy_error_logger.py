"""
caddy_error_logger.py
캐디 오류 자동 기록 시스템 초기화 + S279 오류 기록
EAG-S279-OBSERVE-001 (비오님 지시: S279)

구조:
  /opt/arss/engine/arss-protocol/tools/caddy_error_log/
    caddy_errors.jsonl          — 전체 오류 누적 기록 (append-only)
    caddy_error_summary.json    — 세션별 오류 카운트 요약
    README.md                   — 시스템 설명

기록 형식 (JSONL):
  {
    "timestamp": "ISO8601",
    "session": "S279",
    "error_id": "INC-S279-001",
    "category": "RC-2",          // RC-1~RC-6 중 하나
    "description": "...",
    "root_cause": "...",
    "beo_burden": "...",         // 비오님 부담 내용
    "resolution": "..."          // 수습 조치
  }
"""

import json
import os
from datetime import datetime, timezone

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
LOG_DIR = os.path.join(ARSS_ROOT, "tools/caddy_error_log")
LOG_FILE = os.path.join(LOG_DIR, "caddy_errors.jsonl")
SUMMARY_FILE = os.path.join(LOG_DIR, "caddy_error_summary.json")
README_FILE = os.path.join(LOG_DIR, "README.md")

# ── 디렉토리 초기화 ────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)

# ── README 생성 ────────────────────────────────────────────────────────────────
readme = """# 캐디 오류 자동 기록 시스템

## 목적
캐디가 오류를 저지를 때마다 구조화된 기록을 VPS에 자동 영속 저장한다.
비오님이 언제든 오류 패턴을 조회·분석할 수 있도록 한다.

## 파일 구조
- `caddy_errors.jsonl` : 전체 오류 누적 기록 (append-only, 삭제 금지)
- `caddy_error_summary.json` : 세션별 오류 카운트 요약
- `README.md` : 본 문서

## 오류 카테고리 (RC)
| 코드 | 설명 |
|------|------|
| RC-1 | 기억 기반 실행 — 실측 없이 기억으로 판단·실행 |
| RC-2 | 알려진 제약 미참조 — SESSION_CONTEXT/PROJECT INSTRUCTIONS 규칙 위반 |
| RC-3 | 진단 순서 역전 — 가설 검증 전 해결책 제안 |
| RC-4 | 절차 완료 미확인 — 이전 단계 완료 확인 없이 다음 단계 진행 |
| RC-5 | 옵션 메뉴 제시 — 단일 권고 의무 위반 |
| RC-6 | 기타 |

## 기록 시점
SESSION CLOSE 전 캐디가 해당 세션 오류를 기록한다.
즉각 기록이 필요한 경우 오류 발생 직후 기록한다.

## 생성
EAG-S279-OBSERVE-001 비오님 지시 (S279)
"""
with open(README_FILE, "w", encoding="utf-8") as f:
    f.write(readme)

# ── S279 오류 기록 ─────────────────────────────────────────────────────────────
def utc_now():
    return datetime.now(timezone.utc).isoformat()

def append_error(entry: dict):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# S279 INC-001: PowerShell SSH nested quotes 재발
append_error({
    "timestamp": utc_now(),
    "session": "S279",
    "error_id": "INC-S279-001",
    "category": "RC-2",
    "description": "PowerShell SSH inline python3 -c nested quotes 재사용 — SyntaxError 발생",
    "root_cause": "CADDY_FAILURE_REPORT_S278.md B-4, PROJECT INSTRUCTIONS에 명시된 기존 알려진 제약을 검증 명령 작성 시 참조하지 않음",
    "beo_burden": "오류 메시지 확인 및 재작업 요청 1회",
    "resolution": "verify_observe.py 파일로 교체 — nested quotes 완전 제거"
})

# ── summary 갱신 ───────────────────────────────────────────────────────────────
# 기존 summary 로드
try:
    with open(SUMMARY_FILE, encoding="utf-8") as f:
        summary = json.load(f)
except Exception:
    summary = {"total_errors": 0, "by_session": {}, "by_category": {}}

# S279 카운트 갱신
summary["total_errors"] = summary.get("total_errors", 0) + 1
summary["by_session"]["S279"] = summary["by_session"].get("S279", 0) + 1
summary["by_category"]["RC-2"] = summary["by_category"].get("RC-2", 0) + 1
summary["last_updated"] = utc_now()

# 누적 (S274, S278 기존 오류 반영)
if "S274" not in summary["by_session"]:
    summary["by_session"]["S274"] = 9  # B-1~B-6, A-1~A-2, B-2
if "S278" not in summary["by_session"]:
    summary["by_session"]["S278"] = 3  # C-1, C-2, C-3
    summary["total_errors"] += 12
    summary["by_category"]["RC-1"] = summary["by_category"].get("RC-1", 0) + 4
    summary["by_category"]["RC-2"] = summary["by_category"].get("RC-2", 0) + 4
    summary["by_category"]["RC-3"] = summary["by_category"].get("RC-3", 0) + 2
    summary["by_category"]["RC-4"] = summary["by_category"].get("RC-4", 0) + 2

with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(f"[caddy_error_log] 초기화 완료: {LOG_DIR}")
print(f"[caddy_error_log] S279 INC-001 기록 완료")
print(f"[caddy_error_log] 누적 오류: {summary['total_errors']}건")
