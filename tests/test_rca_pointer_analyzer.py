"""
test_rca_pointer_analyzer.py
EAG: EAG-S232-RCA-POINTER-001
TC-01~TC-08
"""
import json
import pytest
from tools.guard.rca_pointer_analyzer import RCAPointerAnalyzer


@pytest.fixture
def mock_env(tmp_path):
    """테스트용 가상 환경 생성"""
    engine_root = tmp_path / "arss-protocol"
    close_dir = engine_root / "tools" / "close"
    guard_dir = engine_root / "tools" / "guard"

    close_dir.mkdir(parents=True, exist_ok=True)
    guard_dir.mkdir(parents=True, exist_ok=True)

    return {
        "root": str(engine_root),
        "generator": close_dir / "session_close_generator.py",
        "guard": guard_dir / "pointer_guard_s231.py",
        "pointer": engine_root / "SESSION_CONTEXT_POINTER.json",
    }


# TC-01: 파일 전체 없음 → U-01, U-02 UNKNOWN 반환 검증
def test_analyzer_all_unknown_when_files_missing(tmp_path):
    analyzer = RCAPointerAnalyzer(root_path=str(tmp_path))
    res = analyzer.run_full_analysis()
    assert res["U-01"] == "UNKNOWN"
    assert res["U-02"] == "UNKNOWN"


# TC-02: 번들 리스트에 POINTER 파일명 명시 → U-01 PASS
def test_u01_pass_when_pointer_in_bundle(mock_env):
    mock_env["generator"].write_text(
        "bundle_files = ['SESSION_CONTEXT_POINTER.json', 'meta.json']",
        encoding="utf-8",
    )
    analyzer = RCAPointerAnalyzer(root_path=mock_env["root"])
    assert analyzer.analyze_u01() == "PASS"


# TC-03: 번들 리스트에 POINTER 파일명 없음 → U-01 FAIL
def test_u01_fail_when_pointer_missing_in_bundle(mock_env):
    mock_env["generator"].write_text(
        "bundle_files = ['session_journal.json']", encoding="utf-8"
    )
    analyzer = RCAPointerAnalyzer(root_path=mock_env["root"])
    assert analyzer.analyze_u01() == "FAIL"


# TC-04: POINTER 갱신 로직(dump + POINTER 파일명) 존재 → U-02 PASS
def test_u02_pass_when_write_logic_exists(mock_env):
    mock_env["generator"].write_text(
        "with open('SESSION_CONTEXT_POINTER.json', 'w') as f: json.dump(data, f)",
        encoding="utf-8",
    )
    analyzer = RCAPointerAnalyzer(root_path=mock_env["root"])
    assert analyzer.analyze_u02() == "PASS"


# TC-05: POINTER.json에 current_session 키 존재 → U-03 PASS
# 교정: 실제 POINTER.json 스키마 기준 키(current_session) 반영 (T-7 반영)
def test_u03_pass_with_valid_json(mock_env):
    pointer_data = {
        "current_session": 231,
        "chain_tip": "044b887",
        "schema_version": "4.0",
    }
    mock_env["pointer"].write_text(json.dumps(pointer_data), encoding="utf-8")
    analyzer = RCAPointerAnalyzer(root_path=mock_env["root"])
    assert analyzer.analyze_u03() == "PASS"


# TC-06: POINTER.json 손상(invalid JSON) → U-03 FAIL
def test_u03_fail_with_invalid_json(mock_env):
    mock_env["pointer"].write_text("{broken json...", encoding="utf-8")
    analyzer = RCAPointerAnalyzer(root_path=mock_env["root"])
    assert analyzer.analyze_u03() == "FAIL"


# TC-07: generator에 pointer_path 선언 + open(pointer_path) 존재 → U-05 PASS
def test_u05_pass_when_pointer_path_block_exists(mock_env):
    mock_env["generator"].write_text(
        "pointer_path = ROOT / 'SESSION_CONTEXT_POINTER.json'\n"
        "with open(pointer_path, 'w') as f: json.dump(pointer, f)",
        encoding="utf-8",
    )
    mock_env["guard"].write_text("# Guard logic", encoding="utf-8")
    analyzer = RCAPointerAnalyzer(root_path=mock_env["root"])
    assert analyzer.analyze_u05() == "PASS"


# TC-08: generator에 pointer_path 블록 없음 → U-05 FAIL
def test_u05_fail_when_pointer_path_block_missing(mock_env):
    mock_env["generator"].write_text(
        "print('no pointer block here')", encoding="utf-8"
    )
    mock_env["guard"].write_text("# Guard logic", encoding="utf-8")
    analyzer = RCAPointerAnalyzer(root_path=mock_env["root"])
    assert analyzer.analyze_u05() == "FAIL"
