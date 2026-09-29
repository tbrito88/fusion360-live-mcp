import json
import os
import sys

import pytest

from fusion360_live_mcp import autolaunch


def _write_state(tmp_path, entries):
    profile = tmp_path / "Autodesk" / "Autodesk Fusion 360" / "PROFILE1"
    profile.mkdir(parents=True)
    path = profile / "JSLoadedScriptsinfo"
    path.write_text(json.dumps({"loadedScripts": entries}), encoding="utf-8")
    return path


def test_disabled_by_env_in_tests():
    assert autolaunch.enabled("localhost") is False


def test_remote_host_never_autolaunches(monkeypatch):
    monkeypatch.setenv("FUSION360_LIVE_MCP_AUTOLAUNCH", "1")
    assert autolaunch.enabled("192.168.0.10") is False


def test_enable_run_on_startup_flips_only_this_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    ours = autolaunch._addin_script_path().replace("\\", "/")
    path = _write_state(
        tmp_path,
        [
            {"name": "Fusion360LiveMCP", "path": ours, "runOnStartup": False},
            {"name": "Fusion360LiveMCP", "path": "C:/other/Fusion360LiveMCP.py",
             "runOnStartup": False},
        ],
    )
    assert autolaunch.enable_run_on_startup() == 1
    entries = json.loads(path.read_text(encoding="utf-8"))["loadedScripts"]
    assert entries[0]["runOnStartup"] is True
    assert entries[1]["runOnStartup"] is False
    # idempotent
    assert autolaunch.enable_run_on_startup() == 0


def test_enable_run_on_startup_adds_missing_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = _write_state(tmp_path, [])
    assert autolaunch.enable_run_on_startup() == 1
    entries = json.loads(path.read_text(encoding="utf-8"))["loadedScripts"]
    assert entries[0]["name"] == "Fusion360LiveMCP"
    assert entries[0]["runOnStartup"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_entry_through_a_junction_is_recognised(tmp_path, monkeypatch):
    """install-addon.sh links API/AddIns/<name> to addon/; Fusion lists the
    add-in by that path. Auto-launch must reuse that entry, not add a
    second one for the same file (Fusion then showed the add-in twice)."""
    import _winapi

    monkeypatch.setenv("APPDATA", str(tmp_path))
    real = autolaunch._addin_script_path()
    junction = tmp_path / "AddIns" / "Fusion360LiveMCP"
    junction.parent.mkdir()
    _winapi.CreateJunction(os.path.dirname(real), str(junction))
    via = str(junction / os.path.basename(real)).replace("\\", "/")
    path = _write_state(
        tmp_path, [{"name": "Fusion360LiveMCP", "path": via, "runOnStartup": False}]
    )
    assert autolaunch.enable_run_on_startup() == 1
    entries = json.loads(path.read_text(encoding="utf-8"))["loadedScripts"]
    assert len(entries) == 1
    assert entries[0]["runOnStartup"] is True


def test_does_not_restart_running_fusion(monkeypatch):
    monkeypatch.setattr(autolaunch, "fusion_running", lambda: True)
    launched = []
    monkeypatch.setattr(autolaunch, "_launch_fusion", lambda: launched.append(1))
    assert autolaunch.launch_and_wait("localhost", 9876) is False
    assert launched == []



def test_peer_closed_detects_dead_socket():
    import socket

    from fusion360_live_mcp.connection import Fusion360Connection

    a, b = socket.socketpair()
    conn = Fusion360Connection()
    conn._sock = a
    assert conn._peer_closed() is False
    b.close()
    assert conn._peer_closed() is True
    a.close()
