"""The four auth shapes, unit-tested directly on the seam (no DB, no network).

A binding is a plain dict: {injector, location, name, format, secret_field, secret_id}.
env / cli_auth place a string; secret_file / oauth pull a field from a JSON blob.
"""

from __future__ import annotations

import pytest

from treg.infra.upstream.injectors import inject


def _b(**kw) -> dict:
    base = {
        "injector": "env",
        "location": "header",
        "name": "Authorization",
        "format": "Bearer {secret}",
        "secret_field": "access_token",
    }
    base.update(kw)
    return base


def test_env_header():
    h: dict[str, str] = {}
    inject(h, [], _b(), "ABC")
    assert h["Authorization"] == "Bearer ABC"


def test_pasted_newline_is_stripped_before_injection():
    """A credential pasted with its trailing newline (echo/pbpaste) must not reach the header —
    a newline is illegal there and httpx fails with an opaque 502 months after the paste."""
    h: dict[str, str] = {}
    inject(h, [], _b(), "  ABC\n")
    assert h["Authorization"] == "Bearer ABC"


def test_env_query_appends_pair():
    p: list = []
    inject({}, p, _b(location="query", name="api_key", format="{secret}"), "ABC")
    assert p == [("api_key", "ABC")]


def test_query_injection_overrides_caller_param_of_same_name():
    p: list = [("api_key", "caller"), ("keep", "me")]
    inject({}, p, _b(location="query", name="api_key", format="{secret}"), "REAL")
    assert ("keep", "me") in p  # caller's other params preserved
    assert ("api_key", "REAL") in p and ("api_key", "caller") not in p  # injected wins


def test_cli_auth_places_string_like_env():
    h: dict[str, str] = {}
    inject(h, {}, _b(injector="cli_auth"), "TOK")
    assert h["Authorization"] == "Bearer TOK"


def test_secret_file_extracts_default_field():
    h: dict[str, str] = {}
    inject(h, {}, _b(injector="secret_file"), '{"access_token": "AT123", "refresh_token": "RT"}')
    assert h["Authorization"] == "Bearer AT123"


def test_secret_file_custom_field():
    h: dict[str, str] = {}
    inject(h, {}, _b(injector="secret_file", secret_field="token"), '{"token": "XYZ"}')
    assert h["Authorization"] == "Bearer XYZ"


def test_oauth_injects_access_token():
    h: dict[str, str] = {}
    inject(h, {}, _b(injector="oauth"), '{"access_token": "OAT", "expires_at": 123}')
    assert h["Authorization"] == "Bearer OAT"


def test_plain_developer_token_header():
    # google-ads shape: a second binding placing a non-bearer header.
    h: dict[str, str] = {}
    inject(h, {}, _b(name="developer-token", format="{secret}"), "DEV123")
    assert h["developer-token"] == "DEV123"


def test_invalid_json_raises():
    with pytest.raises(ValueError, match="not valid JSON"):
        inject({}, {}, _b(injector="secret_file"), "not json")


def test_missing_field_raises():
    with pytest.raises(ValueError, match="not found"):
        inject({}, {}, _b(injector="secret_file", secret_field="nope"), '{"access_token": "x"}')


def test_unknown_injector_raises():
    with pytest.raises(ValueError, match="unknown injector"):
        inject({}, {}, _b(injector="ghost"), "x")


# ---- token_encode="base64" for HTTP Basic providers (DataForSEO, Moz, PredictLeads) -------------
def test_base64_encode_raw_login_password():
    """A raw `login:password` must be Base64-encoded when token_encode='base64' is set.

    Secrets added via `treg secret add dataforseo` bypass the connect flow that would encode them,
    so the injector must detect and encode a raw value to produce the correct `Basic <b64>` header.
    """
    import base64
    h: dict[str, str] = {}
    binding = _b(name="Authorization", format="Basic {secret}", token_encode="base64")
    inject(h, [], binding, "login:pw")
    expected = "Basic " + base64.b64encode(b"login:pw").decode()
    assert h["Authorization"] == expected


def test_base64_already_encoded_value_is_not_double_encoded():
    """A value that is already Base64-encoded must NOT be encoded again.

    Secrets added via `treg connections connect` are encoded at paste time. The injector must
    detect this and pass the value through unchanged, avoiding double-encoding.
    """
    import base64
    h: dict[str, str] = {}
    blob = base64.b64encode(b"login:pw").decode()
    binding = _b(name="Authorization", format="Basic {secret}", token_encode="base64")
    inject(h, [], binding, blob)
    assert h["Authorization"] == "Basic " + blob, "should not double-encode"


def test_base64_encode_strips_whitespace_before_encoding():
    """Whitespace around the raw value must be stripped before Base64 encoding."""
    import base64
    h: dict[str, str] = {}
    binding = _b(name="Authorization", format="Basic {secret}", token_encode="base64")
    inject(h, [], binding, "  login:pw\n")
    expected = "Basic " + base64.b64encode(b"login:pw").decode()
    assert h["Authorization"] == expected


def test_no_token_encode_passes_value_through():
    """Without token_encode, the value is used as-is (existing behavior)."""
    h: dict[str, str] = {}
    binding = _b(name="X-Api-Key", format="{secret}")
    inject(h, [], binding, "raw-api-key")
    assert h["X-Api-Key"] == "raw-api-key"


def test_base64_encode_query_param():
    """token_encode='base64' also works for query-location credentials."""
    import base64
    p: list = []
    binding = _b(location="query", name="auth", format="Basic {secret}", token_encode="base64")
    inject({}, p, binding, "login:pw")
    expected = "Basic " + base64.b64encode(b"login:pw").decode()
    assert p == [("auth", expected)]
