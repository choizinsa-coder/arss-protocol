#!/bin/bash
# setup_sandbox_dirs.sh
# AIBA SANDBOX 디렉토리 구조 생성 (L2-4)
# SSOT: BRIEFING-DOMI-S142-DESIGN-REQUEST-FINAL

BASE="/opt/arss/engine/arss-protocol/tools/sandbox"

echo "[SANDBOX SETUP] 디렉토리 구조 생성 시작"

mkdir -p "$BASE/domi/active/proposals"
mkdir -p "$BASE/domi/active/findings"

mkdir -p "$BASE/jeni/active/audit"
mkdir -p "$BASE/jeni/active/warnings"

mkdir -p "$BASE/caddy/active/reports"
mkdir -p "$BASE/caddy/active/reviews"
mkdir -p "$BASE/caddy/active/notes"

mkdir -p "$BASE/audit"

echo "[SANDBOX SETUP] 완료"
echo ""
echo "생성된 디렉토리:"
find "$BASE" -type d | sort
