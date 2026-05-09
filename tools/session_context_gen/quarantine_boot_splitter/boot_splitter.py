ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
boot_splitter.py — SESSION_CONTEXT Full/Boot Splitter
PT-S56-001 | AIBA Global Project

⚠️  EXECUTION GATE:
    이 스크립트는 STEP 9에서만 실행 허용.
    STEP 8 dry-run 모드(--dry-run) 외 직접 실행 금지.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.session_context_gen.hash_utils import compute_hash, normalize_json

# ── BOOT 섹션 정의 (boot_validator.py REQUIRED_BOOT_KEYS 기준) ─────────────────
BOOT_SECTIONS = [
    "system_name",
    "system_version",
    "schema_version",
    "architecture",
    "generated_at",
    "session_count",
    "chain",
    "session_reentry",
    "agent_focus",
    "canonical_rules",
    "pending_tasks",
    "state_events",
    "lessons",
    "decisions",
    "archive_refs",
]

# FULL에는 SESSION_CONTEXT.json 전체 포함 (무손실)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────
def _load_ctx(src_path: Path) -> dict:
    with open(src_path, encoding="utf-8") as f:
        return json.load(f)


def _extract_full(ctx: dict) -> dict:
    """FULL = 원본 전체 (무손실 복사)."""
    return dict(ctx)


def _extract_boot(ctx: dict, full_hash: str) -> dict:
    """
    BOOT = BOOT_SECTIONS 추출 + boot_meta 삽입.
    boot_meta.full_hash_ref: FULL CTX의 canonical SHA256
    boot_meta.boot_is_ssot: false 고정
    """
    boot: dict = {}
    for key in BOOT_SECTIONS:
        if key in ctx:
            boot[key] = ctx[key]

    # boot_meta 삽입 (validator CHECK-4, CHECK-5 준수)
    boot["boot_meta"] = {
        "boot_sections": BOOT_SECTIONS,
        "full_hash_ref": full_hash,
        "boot_is_ssot": False,
        "splitter_version": "v1.1",
    }
    return boot


def _write_json(path: Path, data: dict, dry_run: bool) -> str:
    """dry_run=True 시 파일 미생성, hash만 반환."""
    serialized = normalize_json(data)
    artifact_hash = compute_hash(data)
    if not dry_run:
        path.write_text(serialized, encoding="utf-8")
    return artifact_hash


# ── 핵심 분리 함수 ─────────────────────────────────────────────────────────────
def mutate_split(
    src_path: Path,
    full_out: Path,
    boot_out: Path,
    dry_run: bool = False,
) -> dict:
    """
    SESSION_CONTEXT.json → FULL + BOOT 분리.

    반환:
      {
        "ok": True/False,
        "dry_run": bool,
        "full_path": str,
        "boot_path": str,
        "full_hash": str,
        "boot_hash": str,
        "boot_sections_written": [...],
        "full_sections_count": int,
        "error": str (실패 시),
      }
    """
    # 1. 원본 로드
    try:
        ctx = _load_ctx(src_path)
    except Exception as e:
        return {"ok": False, "error": f"SRC_LOAD_FAILED: {e}"}

    # 2. FULL 추출
    full_data = _extract_full(ctx)

    # 3. FULL canonical hash 계산
    full_hash = compute_hash(full_data)

    # 4. BOOT 추출 (boot_meta 삽입)
    boot_data = _extract_boot(ctx, full_hash)

    # 5. 파일 쓰기 (dry_run 시 스킵)
    try:
        full_hash_written = _write_json(full_out, full_data, dry_run)
        boot_hash_written = _write_json(boot_out, boot_data, dry_run)
    except Exception as e:
        return {"ok": False, "error": f"WRITE_FAILED: {e}"}

    # 6. 무결성 확인 (FULL hash 일치)
    if full_hash != full_hash_written:
        return {
            "ok": False,
            "error": f"FULL_HASH_MISMATCH: computed={full_hash}, written={full_hash_written}",
        }

    return {
        "ok": True,
        "dry_run": dry_run,
        "full_path": str(full_out),
        "boot_path": str(boot_out),
        "full_hash": full_hash,
        "boot_hash": boot_hash_written,
        "boot_sections_written": [k for k in boot_data if k != "boot_meta"],
        "full_sections_count": len(full_data),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="boot_splitter — SESSION_CONTEXT 분리 도구")
    parser.add_argument("--src",      required=True, help="원본 SESSION_CONTEXT.json 경로")
    parser.add_argument("--full-out", required=True, help="FULL 출력 경로")
    parser.add_argument("--boot-out", required=True, help="BOOT 출력 경로")
    parser.add_argument("--dry-run",  action="store_true", help="Dry-run (파일 미생성)")
    args = parser.parse_args()

    result = mutate_split(
        src_path=Path(args.src),
        full_out=Path(args.full_out),
        boot_out=Path(args.boot_out),
        dry_run=args.dry_run,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
