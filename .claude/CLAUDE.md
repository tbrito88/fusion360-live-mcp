# Fusion360 Live MCP

## What this is

An MCP server that bridges Claude Code to Autodesk Fusion 360 for CAD automation. Two components:

1. **This repo** — Python MCP server (stdio transport, 92 tools). Claude talks to this.
2. **Fusion360LiveMCP add-in** — installed in Fusion's AddIns folder. Listens on `localhost:9876`.

The MCP server receives tool calls from Claude, forwards them as JSON over TCP to the add-in, and returns results.

## Architecture

```
Claude Code ←(stdio MCP)→ This Server ←(TCP :9876)→ Fusion360LiveMCP Add-in ←(CustomEvent)→ Fusion Main Thread
```

## Development

```bash
uv sync --dev      # install deps
uv run pytest -v   # run tests (490 tests)
uv run ruff check  # lint
```

**While the MCP server is running** it locks `.pyd`/`.dll` files in `.venv`;
a `uv run`/`uv sync` that needs to change packages then fails halfway and
leaves `.venv` missing packages (the live server keeps working, but won't
start again). Run tests in a throwaway env instead:
`UV_PROJECT_ENVIRONMENT=<scratch dir> uv run --dev pytest`.

## Key files

- `src/fusion360_live_mcp/server.py` — MCP server entry point (click CLI), resources, prompts
- `src/fusion360_live_mcp/connection.py` — TCP client to Fusion add-in
- `src/fusion360_live_mcp/tools.py` — 92 tool definitions with annotations
- `src/fusion360_live_mcp/hints.py` — error-classification table (mirror of `addon/server/hints.py`)
- `src/fusion360_live_mcp/mock.py` — mock responses for `--mode mock` testing
- `tests/` — 490 tests covering tools, mock handlers, server routing, connection, annotations

## Adding a new command

1. Add the handler method in the **add-in's** `command_handler.py`
2. Add a tool definition dict in `src/fusion360_live_mcp/tools.py`
3. Add a mock handler in `src/fusion360_live_mcp/mock.py` + dispatch entry
4. Add tool name to the annotation sets if read-only/destructive/idempotent
5. Update `tests/test_tools.py` expected set and add mock test in `tests/test_mock.py`
6. The MCP server forwards tool calls 1:1 — no mapping code needed

## Conventions

- Tool names use snake_case and must match the add-in's command names exactly
- All Fusion API units are in **centimeters** (Fusion's internal unit)
- The add-in uses newline-delimited JSON over TCP
- `ping` is the health check — it never touches the Fusion API
- Every tool has annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`)
- Every tool has a mock handler so `--mode mock` works without Fusion running
