"""
test_exec_runtime_content_b64.py
RC-D regression: write_script content_b64 byte-exact transfer.
EAG-S381-RC-D-B64-INTEGRITY-IMPL-001
"""
import base64
import os
import sys

EXEC_DIR = "/opt/arss/engine/arss-protocol/tools/exec_runtime"
if EXEC_DIR not in sys.path:
    sys.path.insert(0, EXEC_DIR)

import aiba_exec_runtime as er

NL = chr(10)


def test_content_b64_byte_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "CADDY_SANDBOX", str(tmp_path))
    payload = ("a" + chr(13) + chr(10) + "b" + NL + "c" + NL).encode("utf-8")
    b64 = base64.b64encode(payload).decode("ascii")
    ok, reason, spec = er._validate_and_build_cmd("write_script", {"filename": "z.py", "content_b64": b64})
    assert ok, reason
    res = er._run_command("write_script", spec, 10)
    assert res["exit_code"] == 0, res
    with open(spec["target"], "rb") as f:
        written = f.read()
    assert written == payload


def test_content_b64_invalid_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "CADDY_SANDBOX", str(tmp_path))
    ok, reason, spec = er._validate_and_build_cmd("write_script", {"filename": "z.py", "content_b64": "@@@invalid@@@"})
    assert not ok
    assert "content_b64" in reason


def test_content_path_regression(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "CADDY_SANDBOX", str(tmp_path))
    body = "print(1)" + NL
    ok, reason, spec = er._validate_and_build_cmd("write_script", {"filename": "z.py", "content": body})
    assert ok, reason
    res = er._run_command("write_script", spec, 10)
    assert res["exit_code"] == 0
    with open(spec["target"], encoding="utf-8") as f:
        assert f.read() == body


def test_content_missing_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "CADDY_SANDBOX", str(tmp_path))
    ok, reason, spec = er._validate_and_build_cmd("write_script", {"filename": "z.py"})
    assert not ok
    assert "content" in reason
