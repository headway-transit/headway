"""Startup refusal: no key, no server (handoff 0034, design point 1)."""

import pytest

from headway_mcp.client import ConfigError, HeadwayClient
from headway_mcp.server import DEFAULT_API_URL, load_config


def test_refuses_to_start_without_a_key():
    with pytest.raises(ConfigError) as excinfo:
        load_config({})
    message = str(excinfo.value)
    assert "refuses to start" in message
    assert "read:metrics" in message
    assert "POST /machine/keys" in message


def test_refuses_a_non_machine_credential():
    # A session JWT (or anything not hwk_-prefixed) is not a machine key —
    # machine access stays a separate, audited identity.
    with pytest.raises(ConfigError) as excinfo:
        load_config({"HEADWAY_MCP_API_KEY": "eyJhbGciOi.session.token"})
    assert "hwk_" in str(excinfo.value)
    assert "audited" in str(excinfo.value)


def test_blank_key_is_absent_not_valid():
    with pytest.raises(ConfigError):
        load_config({"HEADWAY_MCP_API_KEY": "   "})


def test_accepts_a_machine_key_and_defaults_the_url():
    api_url, api_key = load_config({"HEADWAY_MCP_API_KEY": "hwk_abc"})
    assert api_url == DEFAULT_API_URL
    assert api_key == "hwk_abc"


def test_client_refuses_malformed_key_too():
    # Defense in depth: the client constructor enforces the same rule, so a
    # programmatic caller cannot sidestep load_config.
    with pytest.raises(ConfigError):
        HeadwayClient("http://x", "not-a-machine-key")
