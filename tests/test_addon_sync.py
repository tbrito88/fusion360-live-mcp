"""Drift guards: assert addon-side and package-side mirrors stay in sync.

The Fusion add-in is installed into Fusion's AddIns folder and cannot
import from this package, so a few tables are duplicated:

* ``addon/server/hints.py:_RULES``   ↔  ``src/fusion360_live_mcp/hints.py:_RULES``
* ``CommandHandler._MUTATION_COMMANDS``  ↔  ``mock.py:_MUTATION_MOCKS``

If they drift, agents see different error envelopes / delta payloads
depending on whether they're running against Fusion or mock mode.  These
tests fail loudly the moment a maintainer updates one side without the
other.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module_by_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_class_attr_set(path: Path, class_name: str, attr: str) -> set[str]:
    """Pull ``ClassName.attr`` (a set/frozenset literal) out of *path* via AST.

    Avoids importing the addon module, which depends on Fusion's ``adsk``
    runtime and isn't installable in unit-test environments.
    """
    tree = ast.parse(path.read_text())
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        if cls.name != class_name:
            continue
        for stmt in cls.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == attr for t in stmt.targets):
                continue
            value = stmt.value
            # frozenset({...})  →  unwrap the set literal arg
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "frozenset"
                and value.args
            ):
                return set(ast.literal_eval(value.args[0]))
            return set(ast.literal_eval(value))
    raise AssertionError(f"{class_name}.{attr} not found in {path}")


def test_hints_rules_in_sync():
    """addon and src copies of hints._RULES must be identical."""
    addon_hints = _load_module_by_path(
        REPO_ROOT / "addon" / "server" / "hints.py", "_addon_hints"
    )
    src_hints = _load_module_by_path(
        REPO_ROOT / "src" / "fusion360_live_mcp" / "hints.py", "_src_hints"
    )
    assert addon_hints._RULES == src_hints._RULES, (
        "addon/server/hints.py and src/fusion360_live_mcp/hints.py have drifted. "
        "Update both files in lockstep."
    )


def test_mutation_sets_in_sync():
    """Addon mutation set and mock mutation set must be identical."""
    from fusion360_live_mcp.mock import _MUTATION_MOCKS

    addon_set = _extract_class_attr_set(
        REPO_ROOT / "addon" / "server" / "command_handler.py",
        "CommandHandler",
        "_MUTATION_COMMANDS",
    )
    mock_set = set(_MUTATION_MOCKS)
    assert addon_set == mock_set, (
        f"_MUTATION_COMMANDS (addon) and _MUTATION_MOCKS (mock.py) have drifted.\n"
        f"  only in addon: {sorted(addon_set - mock_set)}\n"
        f"  only in mock:  {sorted(mock_set - addon_set)}"
    )


def _extract_command_dispatch_keys(path: Path) -> set[str]:
    """Pull the string keys of the ``_COMMANDS`` dict literal out of the
    add-in's command_handler via AST (the module can't be imported without
    Fusion's ``adsk`` runtime)."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Attribute) and t.attr == "_COMMANDS" for t in node.targets
        ):
            continue
        if isinstance(node.value, ast.Dict):
            keys = {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if keys:
                return keys
    raise AssertionError(f"_COMMANDS dict literal not found in {path}")


# Commands the add-in dispatches that are intentionally not MCP tools.
_DISPATCH_ONLY = {"reload_handler"}


def test_tools_match_addon_dispatch():
    """Every MCP tool must have an add-in handler, and vice versa.

    This is the drift guard that catches "added a tool to tools.py but
    forgot the CommandHandler entry" (and the reverse) at CI time.
    """
    from fusion360_live_mcp.tools import TOOLS

    tool_names = {t["name"] for t in TOOLS}
    dispatch = (
        _extract_command_dispatch_keys(
            REPO_ROOT / "addon" / "server" / "command_handler.py"
        )
        - _DISPATCH_ONLY
    )
    assert tool_names == dispatch, (
        f"tools.py and CommandHandler._COMMANDS have drifted.\n"
        f"  tools without handler: {sorted(tool_names - dispatch)}\n"
        f"  handlers without tool: {sorted(dispatch - tool_names)}"
    )


# ── mock return shapes ↔ CommandHandler return shapes ─────────────────────
#
# 48 mock handlers once returned keys the real add-in never sends (e.g. mock
# boolean_operation → result_body/target_body, real → feature_name/target/
# tool). An agent developed against mock mode learned the wrong shape. The
# handler's main success return is its literal dict with the most keys; the
# mock may not invent keys outside it.

_SHAPE_EXEMPT = {
    "ping",  # answered by the event bridge, never reaches CommandHandler.ping
    "get_object_info",  # built by _object_info_for_body/_sketch helpers
}


def _literal_return_keys(fn: ast.FunctionDef) -> set[str] | None:
    best = None
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            keys = [k.value for k in n.value.keys if isinstance(k, ast.Constant)]
            complete = len(keys) == len(n.value.keys)
            if complete and (best is None or len(keys) > len(best)):
                best = keys
    return set(best) if best is not None else None


def _all_return_keys(fn: ast.FunctionDef) -> set[str]:
    keys: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            keys |= {k.value for k in n.value.keys if isinstance(k, ast.Constant)}
    return keys


def test_mock_return_keys_are_a_subset_of_the_real_handler():
    handler_path = REPO_ROOT / "addon" / "server" / "command_handler.py"
    mock_path = REPO_ROOT / "src" / "fusion360_live_mcp" / "mock.py"
    handler_src = handler_path.read_text(encoding="utf-8")
    mock_src = mock_path.read_text(encoding="utf-8")
    handler = {
        f.name: f
        for c in ast.parse(handler_src).body
        if isinstance(c, ast.ClassDef) and c.name == "CommandHandler"
        for f in c.body
        if isinstance(f, ast.FunctionDef)
    }
    mock_tree = ast.parse(mock_src)
    mock_funcs = {f.name: f for f in mock_tree.body if isinstance(f, ast.FunctionDef)}
    command_to_mock = {}
    for n in ast.walk(mock_tree):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values, strict=False):
                if (
                    isinstance(k, ast.Constant)
                    and isinstance(v, ast.Name)
                    and v.id in mock_funcs
                ):
                    command_to_mock[k.value] = v.id
    drift = {}
    for cmd, mock_name in command_to_mock.items():
        if cmd in _SHAPE_EXEMPT or cmd not in handler:
            continue
        real = _all_return_keys(handler[cmd])
        if _literal_return_keys(handler[cmd]) is None:
            continue  # handler builds its result dynamically
        invented = _all_return_keys(mock_funcs[mock_name]) - real
        if invented:
            drift[cmd] = sorted(invented)
    assert not drift, f"mock returns keys Fusion never sends: {drift}"
