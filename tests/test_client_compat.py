"""What any MCP client (Claude, Hermes, OpenClaw, Codex, Gemini...) sees.

These go through the MCP SDK's real request handlers in mock mode, so they
catch problems that tests calling the handlers' logic directly cannot (the
resource reads were broken for every client and no test noticed).
"""

from __future__ import annotations

import json
import re

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from fusion360_live_mcp.server import build_app
from fusion360_live_mcp.tools import TOOLS


def _session_call(fn):
    async def run():
        app = build_app("mock", "localhost", 9876)
        async with create_connected_server_and_client_session(app) as session:
            return await fn(session)

    return anyio.run(run)


@pytest.mark.parametrize(
    "uri",
    [
        "fusion360://status",
        "fusion360://design",
        "fusion360://parameters",
        "fusion360://body/Body%201",
        "fusion360://component/Comp1",
    ],
)
def test_resources_are_readable_through_the_sdk(uri):
    result = _session_call(lambda s: s.read_resource(uri))
    data = json.loads(result.contents[0].text)
    assert "error" not in data, data


def test_body_resource_decodes_the_name():
    result = _session_call(lambda s: s.read_resource("fusion360://body/Body%201"))
    assert json.loads(result.contents[0].text)["name"] == "Body 1"


def test_tool_call_round_trip():
    result = _session_call(lambda s: s.call_tool("ping", {}))
    assert not result.isError


def test_unknown_tool_is_reported_as_error():
    result = _session_call(lambda s: s.call_tool("no_such_tool", {}))
    assert result.isError


def test_instructions_state_the_units():
    opts = build_app("mock", "localhost", 9876).create_initialization_options()
    assert "cm" in opts.instructions and "degrees" in opts.instructions


def _walk(schema, path=""):
    yield path, schema
    for name, sub in schema.get("properties", {}).items():
        yield from _walk(sub, f"{path}.{name}")
    for i, sub in enumerate(schema.get("anyOf", [])):
        yield from _walk(sub, f"{path}|{i}")
    if isinstance(schema.get("items"), dict):
        yield from _walk(schema["items"], f"{path}[]")


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_schema_is_portable_across_providers(tool):
    # OpenAI: name charset/length, arrays need items. Gemini: no oneOf/allOf/$ref,
    # enum values must be strings. Hermes prefixes names with mcp_<server>_.
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tool["name"])
    assert len("mcp_fusion360_live_" + tool["name"]) <= 64
    assert tool["inputSchema"].get("type") == "object"
    for path, sub in _walk(tool["inputSchema"]):
        for key in ("oneOf", "allOf", "$ref", "not"):
            assert key not in sub, f"{path}: {key}"
        if sub.get("type") == "array":
            assert "items" in sub, f"{path}: array without items"
        assert all(isinstance(v, str) for v in sub.get("enum", [])), path


def test_every_tool_with_numbers_states_the_units():
    for tool in TOOLS:
        numeric = any(
            sub.get("type") == "number" for _, sub in _walk(tool["inputSchema"])
        )
        if numeric:
            assert "in cm" in tool["description"], tool["name"]
