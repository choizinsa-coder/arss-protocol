"""
tests/conftest.py
v2.0.0 — sys.modules mock 격리 + HC-T Containment Isolation Guard
EAG:  EAG-1 비오(Joshua) 승인 (S192)
설계: 도미 Rev.2 (DESIGN-RESPONSE-DOMI-S192-001)
신뢰: 제니 TRUST_READY PASS (BRIEFING-JENI-S192-001)
"""

import os
import sys
import pytest

# ── Project root sys.path 보장 (importlib mode collection 순서 독립성) ─────────
_CONFTEST_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFTEST_PROJECT_ROOT = os.path.dirname(_CONFTEST_TESTS_DIR)
if _CONFTEST_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _CONFTEST_PROJECT_ROOT)


# ── ENV Gate (REQ-3 Layer 1) ───────────────────────────────────────────────────

def pytest_sessionstart(session):
    """ENV=test 미설정 시 pytest 실행 차단."""
    if os.getenv("ENV") != "test":
        raise SystemExit(
            "[AIBA] pytest blocked: ENV=test required. "
            "Run: $env:ENV='test'; pytest  (PowerShell)"
        )


# ── sys.modules mock 격리 (v1 기존 유지) ──────────────────────────────────────

def pytest_collect_file(parent, file_path):
    """test_mcp_write_gatekeeper.py collect(import) 전 mock 모듈 정리."""
    if file_path.name == "test_mcp_write_gatekeeper.py":
        gk = sys.modules.get("mcp_write_gatekeeper")
        if gk is not None and getattr(gk, "_is_test_mock", False):
            sys.modules.pop("mcp_write_gatekeeper", None)
            sys.modules.pop("mcp_write_server", None)
    return None


def pytest_runtest_setup(item):
    """실행 단계 추가 안전장치."""
    if "test_mcp_write_gatekeeper" in str(item.fspath):
        gk = sys.modules.get("mcp_write_gatekeeper")
        if gk is not None and getattr(gk, "_is_test_mock", False):
            sys.modules.pop("mcp_write_gatekeeper", None)
            sys.modules.pop("mcp_write_server", None)


# ── HC-T Containment Isolation Guard ──────────────────────────────────────────

_PROD_CONTAINMENT_PATH = (
    "/opt/arss/engine/arss-protocol/tools/mcp/mcp_containment_state.json"
)


def _load_containment_module():
    """mcp_containment_state 모듈 로드 (sys.path 주입 포함)."""
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mcp_dir = os.path.join(_project_root, "tools", "mcp")
    for _p in [_mcp_dir, _project_root]:
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import mcp_containment_state as _cs
    return _cs


@pytest.fixture(autouse=True)
def containment_write_guard(monkeypatch, tmp_path):
    """
    HC-T Isolation Guard (REQ-1 + REQ-2) — autouse.

    - CONTAINMENT_STATE_PATH 를 tmp 경로로 강제 교체
    - save_state() 에 production path write 감지 wrapper 설치
    - production path write 시 pytest.fail() 즉시 발동
    """
    try:
        _cs = _load_containment_module()
    except ImportError:
        yield
        return

    test_path = str(tmp_path / "containment_state_guard.json")

    # 상수 monkeypatch (방어 심층 1)
    monkeypatch.setattr(_cs, "CONTAINMENT_STATE_PATH", test_path)

    # save_state wrapper — production path write 감지 (방어 심층 2)
    orig_save_state = _cs.save_state

    def guarded_save_state(state, path=None):
        effective_path = path if path is not None else test_path
        if effective_path == _PROD_CONTAINMENT_PATH:
            pytest.fail(
                "[HC-T Isolation] Direct write to production containment "
                f"state BLOCKED. path={effective_path}"
            )
        return orig_save_state(state, effective_path)

    monkeypatch.setattr(_cs, "save_state", guarded_save_state)

    yield


@pytest.fixture
def containment_state_provider(tmp_path):
    """
    HC-T Containment State Provider (REQ-2) — 선택적.

    containment_write_guard autouse와 안전하게 상호작용.
    명시적 path 격리가 필요한 테스트에서 사용.

    Returns: str — 격리된 테스트용 containment state 경로
    """
    yield str(tmp_path / "containment_state_provider.json")


collect_ignore = ["test_observation_e2e.py"]
