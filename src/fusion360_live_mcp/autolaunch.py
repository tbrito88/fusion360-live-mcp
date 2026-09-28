"""
Auto-launch Fusion 360 (Windows) when the add-in socket is unreachable.

FIX (fork): before this, every session that started with Fusion closed
required the user to open Fusion by hand AND start the add-in from the
Scripts and Add-Ins dialog. Now, when a connect() to localhost fails and
no Fusion process is running, we:

  1. Flip ``runOnStartup`` to true for this add-in in Fusion's own
     add-in state file (``JSLoadedScriptsinfo``). Fusion rewrites that
     file on exit from its in-memory state, so we patch it right before
     each launch (while Fusion is closed) instead of trusting a one-off
     edit.
  2. Start Fusion via its Start-Menu shortcut (the shortcut always points
     at the current webdeploy build, whose hash changes on every update).
  3. Wait for the add-in to open its TCP port.

If Fusion IS already running but the port is closed (add-in stopped),
we do nothing: restarting Fusion could lose unsaved work.

Disable with FUSION360_LIVE_MCP_AUTOLAUNCH=0.
"""

import glob
import json
import logging
import os
import socket
import subprocess
import sys
import time

log = logging.getLogger("fusion360_live_mcp.autolaunch")

_ADDIN_NAME = "Fusion360LiveMCP"
_LAUNCH_WAIT = float(os.environ.get("FUSION360_LIVE_MCP_LAUNCH_WAIT", "240"))


def enabled(host: str) -> bool:
    if os.environ.get("FUSION360_LIVE_MCP_AUTOLAUNCH", "1") == "0":
        return False
    return sys.platform == "win32" and host in ("localhost", "127.0.0.1")


def _addin_script_path() -> str:
    # <repo>/src/fusion360_live_mcp/autolaunch.py -> <repo>/addon/Fusion360LiveMCP.py
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    return os.path.join(repo, "addon", f"{_ADDIN_NAME}.py")


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p.replace("/", os.sep)))



def fusion_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Fusion360.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except Exception:
        return False
    return "Fusion360.exe" in out


def enable_run_on_startup() -> int:
    """Set runOnStartup=true for this add-in in every Fusion user profile.

    Returns the number of entries changed. Only the entry whose path is
    this repo's add-in is touched, so a second installed copy (e.g. in
    API/AddIns) does not also start and fight over the port.
    """
    target = _norm(_addin_script_path())
    pattern = os.path.join(
        os.environ.get("APPDATA", ""), "Autodesk", "Autodesk Fusion 360", "*",
        "JSLoadedScriptsinfo",
    )
    changed = 0
    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            log.warning("Cannot read %s: %s", path, exc)
            continue
        entries = data.get("loadedScripts", [])
        found = False
        # A second entry for the same add-in (e.g. via an API/AddIns junction)
        # is NOT touched here: Fusion rewrites both from the shared manifest
        # on launch (confirmed live). Fusion360LiveMCP.run() steps aside instead.
        for entry in entries:
            if _norm(entry.get("path", "")) == target:
                found = True
                if not entry.get("runOnStartup"):
                    entry["runOnStartup"] = True
                    changed += 1
        if not found:
            entries.append(
                {
                    "name": _ADDIN_NAME,
                    "path": _addin_script_path().replace(os.sep, "/"),
                    "location": 3,
                    "isRemoved": False,
                    "isFavorite": False,
                    "runOnStartup": True,
                }
            )
            data["loadedScripts"] = entries
            changed += 1
        if changed:
            # Fusion's own add-in list: write a sibling file and swap it in,
            # so a crash mid-write can't leave it truncated.
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent="\t")
            os.replace(tmp, path)
    return changed


def _launch_fusion() -> bool:
    lnk = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft", "Windows", "Start Menu", "Programs", "Autodesk",
        "Autodesk Fusion.lnk",
    )
    if os.path.exists(lnk):
        os.startfile(lnk)  # noqa: S606 — user's own installed app
        return True
    launchers = glob.glob(
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Autodesk", "webdeploy", "production", "*", "FusionLauncher.exe",
        )
    )
    if not launchers:
        log.error("Fusion launcher not found")
        return False
    subprocess.Popen([max(launchers, key=os.path.getmtime)])
    return True


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def launch_and_wait(host: str, port: int) -> bool:
    """Start Fusion (if not running) and wait for the add-in's port."""
    if fusion_running():
        log.warning(
            "Fusion is running but the add-in port is closed — not "
            "restarting Fusion (could lose unsaved work)."
        )
        return False
    enable_run_on_startup()
    if not _launch_fusion():
        return False
    log.info("Launched Fusion 360; waiting up to %ss for the add-in", _LAUNCH_WAIT)
    deadline = time.monotonic() + _LAUNCH_WAIT
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(3)
    return False
