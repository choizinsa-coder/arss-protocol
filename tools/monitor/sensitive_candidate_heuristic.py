"""
sensitive_candidate_heuristic.py  (S428 v2 — 오탐 축소)
EAG-S428-SENSITIVE-CANDIDATE-IMPL-001

변경점(v1→v2):
- H2/H3 대상을 설정·데이터 파일로 한정 (소스코드 .py/.sh/.php 제외).
  근거: 소스를 잠그면 import가 깨짐. 오탐 주원.
- H2를 '값이 실제 대입된 형태'만 매칭(언급·정규식 아님).
- H1에서 'shadow' 제거(이 시스템의 그림자 시뮬레이션과 충돌).
- 백업·덤프 파일 및 도구 자기 파일 제외.
원칙: 후보 플래그만. 등급·등록·잠금·본문저장 없음. 읽기전용.
"""
import os
import re
import stat
import time
from pathlib import Path

LAYER1_FORBIDDEN_PATH_PATTERNS = [
    r"\.env", r"\.key$", r"\.pem$", r"\.cert$", r"token", r"secret",
    r"credential", r"oauth", r"private", r"id_rsa", r"id_ed25519",
    r"\.ssh", r"approval",
]
FORBIDDEN_DIR_SEGMENTS = {".git", "venv", ".venv", "__pycache__", ".pytest_cache", "node_modules"}

REASON_H1 = "H1_FILENAME"
REASON_H2 = "H2_CONTENT_PATTERN"
REASON_H3 = "H3_PERMS"
ALLOWED_REASON_CODES = {REASON_H1, REASON_H2, REASON_H3}

# H2/H3 대상: 설정·데이터 파일만 (소스코드 제외)
_DATA_EXTS = {".json", ".yaml", ".yml", ".conf", ".cfg", ".ini", ".toml", ".properties", ".txt", ".xml"}
_MAX_CONTENT_BYTES = 5120
_MAX_FILE_SIZE = 100 * 1024

# H1: 시크릿 저장 파일명 시그니처 (Layer1 미포함, 소스 아님)
_H1_NAME_SIGS = ("htpasswd", "keystore", ".jks", ".p12", ".pfx", ".keytab")

# H2: 값이 실제 대입된 형태(key[:=] 뒤 공백아닌 값 4자+). 매칭 '여부'만 사용, 값 미저장.
_H2_CONTENT_SIGS = [
    re.compile(r"(?:password|passwd|secret[_-]?key|api[_-]?key|apikey|access[_-]?key|client[_-]?secret)\s*[:=]\s*\S{4,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

_COMPILED_FORBIDDEN = [re.compile(p) for p in LAYER1_FORBIDDEN_PATH_PATTERNS]
_SELF_FILES = {"sensitive_candidate_heuristic.py", "sensitive_candidate_scanner.py", "sensitive_candidates.json"}


def is_layer1_blocked(path_str):
    low = path_str.lower()
    return any(rx.search(low) for rx in _COMPILED_FORBIDDEN)


def _is_backup_or_dump(name_low):
    return (name_low.endswith("bak") or "_bak" in name_low or ".bak" in name_low
            or ".pre_" in name_low or name_low.endswith(".dump"))


def _in_forbidden_dir(p):
    return bool(set(p.parts) & FORBIDDEN_DIR_SEGMENTS)


def _check_h1(p):
    name = p.name.lower()
    return any(sig in name for sig in _H1_NAME_SIGS)


def _check_h2(p):
    if p.suffix.lower() not in _DATA_EXTS:
        return False
    try:
        if p.stat().st_size > _MAX_FILE_SIZE:
            return False
        with open(p, "rb") as fh:
            chunk = fh.read(_MAX_CONTENT_BYTES)
        text = chunk.decode("utf-8", errors="ignore")
    except Exception:
        return False
    return any(rx.search(text) for rx in _H2_CONTENT_SIGS)


def _check_h3(p):
    if p.suffix.lower() not in _DATA_EXTS:
        return False
    try:
        mode = p.stat().st_mode
    except Exception:
        return False
    return bool(mode & (stat.S_IWGRP | stat.S_IWOTH))


def evaluate_file(p):
    name_low = p.name.lower()
    if name_low in _SELF_FILES:
        return []
    if _is_backup_or_dump(name_low):
        return []
    if is_layer1_blocked(str(p)):
        return []
    codes = []
    if _check_h1(p):
        codes.append(REASON_H1)
    if _check_h2(p):
        codes.append(REASON_H2)
    if _check_h3(p):
        codes.append(REASON_H3)
    return [c for c in codes if c in ALLOWED_REASON_CODES]


def scan_tree(root, max_candidates=500):
    root_path = Path(root)
    candidates = []
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for dirpath, dirnames, filenames in os.walk(root_path):
        dp = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d not in FORBIDDEN_DIR_SEGMENTS]
        if _in_forbidden_dir(dp):
            continue
        for fn in filenames:
            fp = dp / fn
            try:
                if fp.is_symlink() or not fp.is_file():
                    continue
            except Exception:
                continue
            codes = evaluate_file(fp)
            if codes:
                candidates.append({
                    "path": str(fp),
                    "reason_codes": sorted(codes),
                    "detected_at": now,
                })
                if len(candidates) >= max_candidates:
                    return candidates
    return candidates
