"""
tests/conftest.py — sys.modules mock 격리
Collection 단계에서 test_mcp_write_gatekeeper.py import 전 mock 정리.
"""
import sys


def pytest_collect_file(parent, file_path):
    """test_mcp_write_gatekeeper.py collect(import) 전 mock 모듈 정리."""
    if file_path.name == "test_mcp_write_gatekeeper.py":
        gk = sys.modules.get("mcp_write_gatekeeper")
        if gk is not None and getattr(gk, "_is_test_mock", False):
            sys.modules.pop("mcp_write_gatekeeper", None)
            sys.modules.pop("mcp_write_server", None)
    return None  # pytest 기본 collection 처리 유지


def pytest_runtest_setup(item):
    """실행 단계 추가 안전장치."""
    if "test_mcp_write_gatekeeper" in str(item.fspath):
        gk = sys.modules.get("mcp_write_gatekeeper")
        if gk is not None and getattr(gk, "_is_test_mock", False):
            sys.modules.pop("mcp_write_gatekeeper", None)
            sys.modules.pop("mcp_write_server", None)
