import importlib.util, os, pytest

ROOT = "/opt/arss/engine/arss-protocol"
BRIDGE = os.path.join(ROOT, "tools/mcp/mcp_http_bridge.py")
NGINX = "/etc/nginx/sites-enabled/arss-mcp"


def _load():
    spec = importlib.util.spec_from_file_location("bridgemod_s457", BRIDGE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _handler_src():
    src = open(BRIDGE).read()
    i = src.index("def _handle_agent_request")
    j = src.index("\ndef ", i + 10)
    return src[i:j]


def test_c1_handler_resolves_actor_from_token():
    assert "_resolve_actor_from_token" in _handler_src()


def test_c2_handler_rejects_actor_mismatch():
    s = _handler_src()
    assert "actor_mismatch" in s
    assert "403" in s


def test_c3_external_token_rejected():
    m = _load()
    m._OAUTH_CLIENTS["x-ext-s457"] = {"actor_id": "external"}
    m._OAUTH_TOKENS["tok-ext-s457"] = {"client_id": "x-ext-s457", "expires_at": 9999999999}
    actor, err = m._resolve_actor_from_token("Bearer tok-ext-s457")
    assert actor is None
    assert err is not None


def test_c4_domi_token_resolves_to_domi():
    m = _load()
    m._OAUTH_CLIENTS["x-domi-s457"] = {"actor_id": "domi"}
    m._OAUTH_TOKENS["tok-domi-s457"] = {"client_id": "x-domi-s457", "expires_at": 9999999999}
    actor, err = m._resolve_actor_from_token("Bearer tok-domi-s457")
    assert actor == "domi"
    assert err is None


def test_c5_mcp_endpoint_ip_restricted():
    if not os.access(NGINX, os.R_OK):
        pytest.skip("nginx conf not readable")
    s = open(NGINX).read()
    i = s.index("location /mcp {")
    assert "deny all;" in s[i:i + 600]


def test_c6_write_file_not_publicly_exposed():
    if not os.access(NGINX, os.R_OK):
        pytest.skip("nginx conf not readable")
    assert "/domi/write_file" not in open(NGINX).read()
