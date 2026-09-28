"""
TCP connection to the Fusion360LiveMCP add-in running inside Fusion 360.

The add-in listens on localhost:9876 by default and speaks
newline-delimited JSON. Override via env vars FUSION360_LIVE_MCP_HOST /
FUSION360_LIVE_MCP_PORT for cross-machine setups (e.g. MCP server on a
Mac Mini connecting to Fusion running on a Windows PC).
"""

import json
import logging
import os
import select
import socket
import time
from typing import Any

from . import autolaunch
from .hints import classify as _classify
from .tools import _READ_ONLY as _RETRY_SAFE

log = logging.getLogger("fusion360_live_mcp.connection")

_DEFAULT_HOST = os.environ.get("FUSION360_LIVE_MCP_HOST", "localhost")


def _default_port() -> int:
    raw = os.environ.get("FUSION360_LIVE_MCP_PORT", "9876")
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid FUSION360_LIVE_MCP_PORT %r — falling back to 9876", raw)
        return 9876


_DEFAULT_PORT = _default_port()
_RECV_BUF = 65536
# Must exceed the add-in's 30s bridge timeout so a structured TIMEOUT
# response arrives before the client gives up.
_TIMEOUT = 45.0
_PING_TIMEOUT = 5.0
_MAX_RETRIES = 2
_RETRY_DELAY = 1.0  # seconds between reconnect attempts
# The add-in honours params.timeout_s (clamped to this) instead of its 30 s.
_MAX_BRIDGE_TIMEOUT = 600.0
_TIMEOUT_MARGIN = 15.0


def _socket_timeout(params: dict[str, Any] | None, default: float) -> float:
    """Socket wait for a command: must outlast the add-in's bridge wait,
    which a caller can raise with params.timeout_s."""
    raw = (params or {}).get("timeout_s")
    if raw is None:
        return default
    try:
        bridge = max(1.0, min(float(raw), _MAX_BRIDGE_TIMEOUT))
    except (TypeError, ValueError):
        return default
    return max(default, bridge + _TIMEOUT_MARGIN)


class FusionError(RuntimeError):
    """Structured error reported by the add-in (or a timed-out command)."""

    def __init__(
        self, message: str, error_kind: str = "UNKNOWN", hints: list[str] | None = None
    ):
        super().__init__(message)
        self.error_kind = error_kind
        self.hints = hints or []


class Fusion360Connection:
    """Persistent TCP connection to the Fusion 360 add-in socket server."""

    def __init__(self, host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT):
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        if self._sock is not None:
            return True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(_PING_TIMEOUT)
            s.connect((self.host, self.port))
            self._sock = s
            # Re-arm auto-launch: if Fusion is closed again later in this
            # session, the next failed connect should reopen it.
            self._autolaunch_tried = False
            log.info("Connected to Fusion 360 at %s:%s", self.host, self.port)
            return True
        except Exception as exc:
            log.error("Failed to connect: %s", exc)
            self._sock = None
            if self._try_autolaunch():
                return self.connect()
            return False

    def _try_autolaunch(self) -> bool:
        """Open Fusion (once per connection object) if it isn't running."""
        if getattr(self, "_autolaunch_tried", False) or not autolaunch.enabled(
            self.host
        ):
            return False
        self._autolaunch_tried = True
        return autolaunch.launch_and_wait(self.host, self.port)

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def reconnect(self) -> bool:
        """Drop the existing socket and open a fresh one."""
        self.disconnect()
        return self.connect()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Send a ping and return True if the add-in responds.

        Uses a short timeout and no retries so it stays a cheap health
        check even when the Fusion main thread is wedged.
        """
        try:
            self.send_command("ping", retries=0, timeout=_PING_TIMEOUT)
            return True
        except Exception:
            return False

    def ensure_connected(self) -> bool:
        """Verify the connection is alive (via ping), reconnect if not."""
        if self._sock is not None and self.ping():
            return True
        # Connection is dead — try to reconnect
        log.warning("Connection lost, attempting reconnect...")
        return self.reconnect()

    # ------------------------------------------------------------------
    # Send / receive
    # ------------------------------------------------------------------

    def send_command(
        self,
        command_type: str,
        params: dict[str, Any] | None = None,
        retries: int = _MAX_RETRIES,
        timeout: float = _TIMEOUT,
    ) -> dict:
        """Send a JSON command and block until a JSON response arrives.

        On connection failure, read-only commands are retried up to
        ``retries`` times with a fresh socket.  Mutation commands are
        **never** retried after a send was attempted: the add-in may have
        queued or executed the command already, and re-sending could apply
        the change twice.
        """
        if self._sock is not None and self._peer_closed():
            # FIX (fork): after Fusion restarts, the cached socket is dead
            # and the first command failed with WinError 10053 — and a
            # mutation is (rightly) never retried, so it surfaced as an
            # error. Detecting the close BEFORE sending makes reconnecting
            # safe: nothing has reached the add-in yet.
            log.info("Peer closed the socket; reconnecting before send")
            self.disconnect()
        if not self._sock and not self.connect():
            raise ConnectionError(
                "Not connected to Fusion 360.  Make sure the add-in is running."
            )

        payload = (
            json.dumps(
                {
                    "type": command_type,
                    "params": params or {},
                }
            )
            + "\n"
        )

        # Only commands known to be read-only may be re-sent: anything else
        # (sketch curves, parameters, exports...) could run twice.
        is_mutation = command_type not in _RETRY_SAFE
        timeout = _socket_timeout(params, timeout)
        try:
            self._sock.sendall(payload.encode("utf-8"))
            self._sock.settimeout(timeout)
            response = self._recv_json()
        except (socket.timeout, OSError, ConnectionError) as exc:
            log.error("Socket error: %s", exc)
            self.disconnect()
            if is_mutation:
                raise FusionError(
                    f"{command_type}: no response from Fusion "
                    f"({exc}). The command was NOT retried, but it may "
                    "still have executed — call get_scene_info to check "
                    "the design state before trying again.",
                    error_kind="TIMEOUT",
                    hints=[
                        "Call get_scene_info to see whether the "
                        "operation partially applied.",
                        "Long operations (CAM toolpaths, complex fillets) "
                        "exceed the add-in's 30s bridge timeout — split "
                        "them into smaller steps.",
                    ],
                ) from exc
            if retries > 0:
                log.info("Retrying (%d left)...", retries)
                time.sleep(_RETRY_DELAY)
                if self.connect():
                    return self.send_command(
                        command_type, params, retries=retries - 1, timeout=timeout
                    )
            raise ConnectionError(f"Lost connection to Fusion 360: {exc}") from exc

        if response.get("status") == "error":
            message = response.get("message", "Unknown error")
            kind = response.get("error_kind")
            hints = response.get("hints")
            if kind is None:
                kind, classified_hints = _classify(message)
                if hints is None:
                    hints = classified_hints
            raise FusionError(message, error_kind=kind, hints=hints)

        return response.get("result", {})

    def _peer_closed(self) -> bool:
        """True if the add-in side has closed (or reset) the socket.

        The protocol is strictly request/response, so an idle socket that
        is readable can only mean EOF or an error.
        """
        try:
            readable, _, _ = select.select([self._sock], [], [], 0)
            if not readable:
                return False
            return self._sock.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _recv_json(self) -> dict:
        """Read newline-delimited JSON from the socket."""
        buf = b""
        while True:
            chunk = self._sock.recv(_RECV_BUF)
            if not chunk:
                raise ConnectionError("Connection closed by Fusion 360")
            buf += chunk

            # Look for a complete newline-terminated message
            if b"\n" in buf:
                line, _rest = buf.split(b"\n", 1)
                return json.loads(line)

            # Fallback: try to parse the whole buffer as JSON
            try:
                return json.loads(buf)
            except json.JSONDecodeError:
                continue


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_connection: Fusion360Connection | None = None


def get_connection(
    *, host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT
) -> Fusion360Connection:
    """Return (and lazily create) a shared connection.

    If the cached connection targets a different host/port than
    requested, it is dropped and recreated — silently reusing the wrong
    endpoint is worse than reconnecting.
    """
    global _connection
    if _connection is not None and (
        _connection.host != host or _connection.port != port
    ):
        log.info(
            "Endpoint changed (%s:%s -> %s:%s), reconnecting",
            _connection.host,
            _connection.port,
            host,
            port,
        )
        reset_connection()
    if _connection is None:
        _connection = Fusion360Connection(host, port)
        _connection.connect()
    return _connection


def reset_connection():
    """Drop the cached connection (e.g. after an error)."""
    global _connection
    if _connection:
        _connection.disconnect()
    _connection = None
