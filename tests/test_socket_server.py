"""The add-in's TCP server must not run commands smuggled in by a web page.

A page can make the browser POST to http://localhost:9876; the body of that
HTTP request is valid JSON and used to be dispatched like a real command
(including execute_code). ``socket_server.py`` is loaded by path with a stub
parent package, since the real one imports Fusion's ``adsk`` runtime.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import socket
import sys
import time
import types
from pathlib import Path

import pytest

ADDON_SERVER = Path(__file__).resolve().parent.parent / "addon" / "server"
COMMAND = {"type": "execute_code", "params": {"code": "print(1)"}}


def _load_server_class():
    pkg = types.ModuleType("_addon_server_stub")
    pkg.__path__ = [str(ADDON_SERVER)]
    pkg.get_logger = lambda name: logging.getLogger(f"test.{name}")
    sys.modules["_addon_server_stub"] = pkg
    spec = importlib.util.spec_from_file_location(
        "_addon_server_stub.socket_server", ADDON_SERVER / "socket_server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Fusion360LiveMCPServer


class _RecordingBridge:
    def __init__(self):
        self.commands = []

    def submit(self, command):
        self.commands.append(command)
        return {"status": "success", "result": "ran"}


@pytest.fixture
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    bridge = _RecordingBridge()
    srv = _load_server_class()(bridge, host="127.0.0.1", port=port)
    srv.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    yield port, bridge
    srv.stop()


def _send(port: int, data: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
        s.sendall(data)
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := s.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


_BODY = json.dumps(COMMAND)


@pytest.mark.parametrize("body", [_BODY, "\n" + _BODY + "\n"])
def test_http_request_from_browser_is_not_dispatched(server, body):
    port, bridge = server
    request = (
        "POST / HTTP/1.1\r\nHost: localhost\r\nOrigin: https://evil.example\r\n"
        f"Content-Type: text/plain\r\nContent-Length: {len(body)}\r\n\r\n{body}"
    )
    _send(port, request.encode())
    time.sleep(0.2)
    assert bridge.commands == []


def test_newline_delimited_json_still_works(server):
    port, bridge = server
    reply = _send(port, (json.dumps(COMMAND) + "\n").encode())
    assert bridge.commands == [COMMAND]
    assert json.loads(reply.splitlines()[0])["result"] == "ran"
