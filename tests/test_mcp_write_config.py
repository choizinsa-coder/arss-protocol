# RULE-8 ASSERTION — S181 Batch-11B
# Module: mcp_write_config
# Task: P4-C4 Phase-beta Batch-11B
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest
from tools.mcp.mcp_write_config import (
    TOKEN_TTL,
    SOFT_TOKEN_TTL,
    FORBIDDEN_EXTENSIONS,
    FORBIDDEN_PATH_PREFIXES,
)


def test_config_token_ttl_is_600():
    """TOKEN_TTL 불변성 — 정확히 600이어야 한다."""
    assert TOKEN_TTL == 600


def test_config_soft_token_ttl_is_480_and_below_token_ttl():
    """SOFT_TOKEN_TTL == 480 이고 TOKEN_TTL 미만이어야 한다."""
    assert SOFT_TOKEN_TTL == 480
    assert SOFT_TOKEN_TTL < TOKEN_TTL


def test_config_denylist_collections_nonempty_and_denylist_shaped():
    """FORBIDDEN_EXTENSIONS, FORBIDDEN_PATH_PREFIXES 비어있지 않고 denylist 구조."""
    # 비어있지 않음
    assert len(FORBIDDEN_EXTENSIONS) > 0
    assert len(FORBIDDEN_PATH_PREFIXES) > 0
    # denylist 구조 — .py 포함 여부 (고위험 확장자 반드시 차단)
    assert ".py" in FORBIDDEN_EXTENSIONS
    # path prefix는 문자열 컬렉션
    assert all(isinstance(p, str) for p in FORBIDDEN_PATH_PREFIXES)
    # SESSION_CONTEXT 관련 경로 차단 포함 여부
    assert any("SESSION_CONTEXT" in p for p in FORBIDDEN_PATH_PREFIXES)
