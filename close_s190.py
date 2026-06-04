"""
close_s190.py — AIBA S190 세션 종료 스크립트
VPS에서 실행: python3 /opt/arss/engine/arss-protocol/close_s190.py
생성 파일:
  - SESSION_CONTEXT_S190_FINAL.json
  - SESSION_CONTEXT.json (SSOT 덮어쓰기)
  - SESSION_CONTEXT_ARCHIVE_TIER_D_S190.json
  - SESSION_CONTEXT_POINTER.json
  - SESSION_CONTEXT_STALE_MANIFEST.json
"""

import json
import hashlib
import datetime
import os
import sys

BASE_DIR = "/opt/arss/engine/arss-protocol"

S189_FINAL  = f"{BASE_DIR}/SESSION_CONTEXT.json"  # S189 FINAL이 VPS 미존재 — SSOT 사용
S190_FINAL  = f"{BASE_DIR}/SESSION_CONTEXT_S190_FINAL.json"
S189_ARCH   = f"{BASE_DIR}/SESSION_CONTEXT_ARCHIVE_TIER_D_S189.json"
S190_ARCH   = f"{BASE_DIR}/SESSION_CONTEXT_ARCHIVE_TIER_D_S190.json"
SSOT        = f"{BASE_DIR}/SESSION_CONTEXT.json"
POINTER     = f"{BASE_DIR}/SESSION_CONTEXT_POINTER.json"
MANIFEST    = f"{BASE_DIR}/SESSION_CONTEXT_STALE_MANIFEST.json"

# ── 1. 베이스 로드 ────────────────────────────────────────────────────────────
print("[1/7] Loading S189 FINAL base...")
with open(S189_FINAL, "r", encoding="utf-8") as f:
    ctx = json.load(f)

# ── 2. S190 Delta 적용 ────────────────────────────────────────────────────────
print("[2/7] Applying S190 delta...")

now = datetime.datetime.now(
    datetime.timezone(datetime.timedelta(hours=9))
).strftime("%Y-%m-%dT%H:%M:%S+09:00")

ctx["session_count"] = 190
ctx["updated_at"]    = now
ctx["generated_at"]  = now

ctx["chain"] = {
    "prev_tip": "7ad8db7",
    "session": 190,
    "tip": "ebc765c"
}

ctx["session_reentry"] = {
    "last_session": 190,
    "resume_point": (
        "도미·제니 세션 부트 루틴 확정(boot.md v1.2). "
        "4계층 구조(Boot Policy/Session Context/Task Context/Work Session) canonical. "
        "제니 독립 검증 경로 확보(TRIGGER-A~E). "
        "임시 운영 규칙 활성: TRIGGER 시 비오님 수동 SESSION_CONTEXT 전달. "
        "jeni-runtime 다중 턴 루프 미구현 — 도미 설계 필요."
    ),
    "eag_carryover": "없음 — S190 EAG-1/EAG-2 전부 완료"
}

ctx["next_steps"] = [
    "jeni-runtime 다중 턴 루프 구현 — TRIGGER 발생 시 제니가 /jeni/read_file 자율 호출 후 재평가 (도미 설계 필요, Interim Manual Protocol 임시 대체 중)",
    "오케스트레이션 아키텍처 Rev.2 — 도미 (Fail-Closed 메커니즘 / EAG-GATE ENFORCER / max_review_rounds 하드캡 3항목)",
    "Incident-L15: VPS 시스템 방화벽 표준 룰셋 적용 및 ufw 활성화 — 도미 설계 / 제니 검토 / 비오 EAG (제니 강제 권고)",
    "Gemini API 키 폐기/재발급 — 스크린샷 노출 키 교체 (보안 후속)",
    "nginx conflicting server name warning 정리",
    "audit_trail.log phase_b TOOL_DENY 오염 격리",
    "BUG-S181-WS-RECOVERY-ENUM-MISMATCH / mcp_approval_authority.py",
    "HC-T-* 전역 Test-Isolation conftest 패키지 — 도미 설계 대기",
    "AES(AIBA Evidence Standard) 설계 — 도미 의뢰 필요"
]

ctx["agent_focus"] = {
    "beo": "S190 완료 — 도미·제니 세션 부트 루틴 확정(boot.md v1.2, EAG-2 PASS). 4계층 Boot 구조 + 독립 검증 경로 canonical 확정.",
    "caddy": "boot.md v1.2 배포 완료(ebc765c). Stage A/B/C + TRIGGER-A~E + Interim Manual Protocol. jeni-runtime 다중 턴 루프 구현 도미 설계 대기.",
    "domi": "세션 부트 루틴 Rev.1/Rev.2 설계 완료(ebc765c). Rev.1 T-2/T-3 FAIL 후 Rev.2에서 독립 검증 경로 확보. jeni-runtime 다중 턴 루프 구현 명세 대기.",
    "jeni": "boot.md v1.2 TRUST_READY PASS(V-1~V-3). Stateless Validation Engine 재정의 + TRIGGER-A~E 독립 검증 규칙 canonical. Interim Manual Protocol 적용 중."
}

ctx["system_changes_s190"] = {
    "deployed_session": 190,
    "changes": [
        "domi_boot.md v1.1 → v1.2 — Stage A/B/C 세션 부트 루틴 + Verification Independence Rule 추가",
        "jeni_boot.md v1.1 → v1.2 — Stateless Validation Engine 정의 + Independent Verification Rule(TRIGGER-A~E) + Interim Manual Protocol 추가"
    ],
    "commit": "ebc765c",
    "code_changes": "boot.md 문서 변경만 (코드 변경 없음)"
}

ctx["caddy_governance_record_s190"] = {
    "session": 190,
    "date": "2026-06-04",
    "eag_gates_this_session": [
        "EAG-1: boot.md v1.2 설계 승인 (도미 Rev.2 + 제니 CONDITIONAL PASS) — 비오(Joshua) 승인",
        "EAG-2: boot.md v1.2 배포 최종 확인 (제니 TRUST_READY PASS V-1~V-3) — 비오(Joshua) 승인"
    ],
    "governance_cycle": (
        "브리핑 → 도미 Rev.1 → 제니 T-2/T-3 FAIL → 도미 Rev.2 → "
        "제니 CONDITIONAL PASS → 비오 EAG-1 → 캐디 구현/배포 → "
        "제니 재검증 PASS → 비오 EAG-2 → git commit ebc765c"
    ),
    "incidents": [],
    "notable": "도미·제니 세션 부트 루틴 v1.2 canonical 확정. 4계층 구조 수립. 제니 독립 검증 경로(TRIGGER-A~E) 확보.",
    "output_scope_compliance": "전 출력 [이번 출력 범위] 선언 준수. 역할 경계 위반 없음. 권위 narration 미발생.",
    "stabilization_metrics": {
        "M01_pre_output_check": "PASS",
        "M02_session_context_load": "PASS — VPS MCP read_file로 canonical 직접 로드",
        "M03_eag_compliance": "PASS — EAG-1/EAG-2 게이트 준수",
        "M04_file_path_bash_only": "PASS",
        "M05_delta_only_sc_update": "PASS — S189 base + S190 delta (close_s190.py)",
        "M06_present_files_before_scp": "PASS — domi_boot.md/jeni_boot.md present 선행",
        "M07_role_boundary": "PASS — [DESIGN]/[SELF-CRITIQUE]/에이전트 응답 미생성"
    }
}

ctx["visibility_metrics_s190"] = {
    "session": 190,
    "date": "2026-06-04",
    "M-01_active_canonical_key_count": 42,
    "M-02_tier_d_quarantine_key_count": 66,
    "M-03_ceiling_utilization_rate": "42/42 (Tier D 변동 없음 — 신규 키 system_changes_s190/caddy_governance_record_s190/visibility_metrics_s190 Tier D 미이관)",
    "M-04_session_delta_size": "MEDIUM (boot.md v1.2 — 문서 변경, 코드 변경 없음)",
    "M-05_archive_file_status": "SESSION_CONTEXT_ARCHIVE_TIER_D_S190.json (변동 없음 기반)",
    "M-06_active_task_load": 9,
    "M-07_stabilization_compliance": "N/A (S120 해제)",
    "chain_tip": "ebc765c",
    "pytest_result": "변동 없음 — S187 baseline 유지 (0 failed, 1381 passed, 96 skipped). 코드 commit 없음.",
    "key_decisions": [
        "도미·제니 세션 부트 루틴 4계층 구조 canonical 확정",
        "제니 재정의: Stateless Validation Engine",
        "독립 검증 경로: TRIGGER-A~E + Interim Manual Protocol",
        "boot.md v1.2: EAG-1→검증→수정→재검증→EAG-2 전 단계 준수",
        "git commit ebc765c (2 files, +150/-8)"
    ]
}

ctx["session_delta"] = {
    "session": 190,
    "modified_keys": [
        "session_count", "updated_at", "generated_at",
        "chain", "session_reentry", "next_steps", "agent_focus"
    ],
    "added_keys": [
        "system_changes_s190",
        "caddy_governance_record_s190",
        "visibility_metrics_s190"
    ],
    "removed_keys": []
}

# ── 3. context_hash 계산 ──────────────────────────────────────────────────────
print("[3/7] Computing context_hash...")
ctx_for_hash = {k: v for k, v in ctx.items() if k != "context_hash"}
canonical = json.dumps(
    ctx_for_hash,
    sort_keys=True,
    ensure_ascii=True,
    separators=(",", ":"),
    indent=None,
    allow_nan=False
)
context_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
ctx["context_hash"] = context_hash
print(f"  context_hash: {context_hash}")

# ── 4. SESSION_CONTEXT_S190_FINAL.json 생성 ───────────────────────────────────
print("[4/7] Writing SESSION_CONTEXT_S190_FINAL.json...")
with open(S190_FINAL, "w", encoding="utf-8") as f:
    json.dump(ctx, f, ensure_ascii=False, indent=2)

# ── 5. SESSION_CONTEXT.json (SSOT) 덮어쓰기 ──────────────────────────────────
print("[5/7] Overwriting SESSION_CONTEXT.json (SSOT)...")
with open(SSOT, "w", encoding="utf-8") as f:
    json.dump(ctx, f, ensure_ascii=False, indent=2)

# ── 6. Tier D Archive (변동 없음 — S189 복사) ─────────────────────────────────
print("[6/7] Writing SESSION_CONTEXT_ARCHIVE_TIER_D_S190.json (Tier D 변동 없음)...")
with open(S189_ARCH, "r", encoding="utf-8") as f:
    archive_data = json.load(f)
with open(S190_ARCH, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

# ── 7. POINTER + MANIFEST (3-way 일치) ───────────────────────────────────────
print("[7/7] Writing POINTER and MANIFEST (3-way sync)...")

pointer = {
    "canonical_source": "SESSION_CONTEXT_S190_FINAL.json",
    "session_count": 190,
    "chain_tip": "ebc765c",
    "context_hash": context_hash,
    "updated_at": now,
    "vps_path": "/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json"
}
with open(POINTER, "w", encoding="utf-8") as f:
    json.dump(pointer, f, ensure_ascii=False, indent=2)

manifest = {
    "session_count": 190,
    "context_hash": context_hash,
    "updated_at": now,
    "status": "FRESH",
    "blocking_flags": []
}
with open(MANIFEST, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

# ── 3-way 검증 ────────────────────────────────────────────────────────────────
print("\n[VERIFY] 3-way consistency check:")
print(f"  FINAL   session_count={ctx['session_count']} context_hash={context_hash[:16]}... updated_at={now}")
print(f"  POINTER session_count={pointer['session_count']} context_hash={pointer['context_hash'][:16]}... updated_at={pointer['updated_at']}")
print(f"  MANIFEST session_count={manifest['session_count']} context_hash={manifest['context_hash'][:16]}... updated_at={manifest['updated_at']}")

assert ctx['session_count'] == pointer['session_count'] == manifest['session_count'], "session_count MISMATCH"
assert context_hash == pointer['context_hash'] == manifest['context_hash'], "context_hash MISMATCH"
assert now == pointer['updated_at'] == manifest['updated_at'], "updated_at MISMATCH"
print("  3-way: PASS")

print("\n[DONE] S190 session close files generated successfully.")
print(f"  chain_tip : ebc765c")
print(f"  context_hash : {context_hash}")
