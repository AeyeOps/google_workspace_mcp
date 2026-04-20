#!/usr/bin/env python3
"""Register the local workspace-mcp binary as Claude Code's `workspace-mm` MCP.

Idempotent: any pre-existing `workspace-mm` registration is removed first so
re-running the target after a rebuild just re-points it.

Invoked by the `mcp-register` Makefile target with the absolute path to the
local `.venv/bin/workspace-mcp` as the sole argument.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MCP_NAME = "workspace-mm"
TOOL_TIER = "complete"

# Where we expect the OAuth client_secret.json to live. Mirrors the
# gmail-mm convention (~/.gmail-mcp/gcp-oauth.keys.json). Wired into the
# MCP registration via GOOGLE_CLIENT_SECRET_PATH so the local fork can
# initiate new OAuth flows (not just refresh existing tokens).
CLIENT_SECRET_PATH = Path.home() / ".workspace-mm-mcp" / "client_secret.json"


def fail(msg: str, code: int = 1) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return code


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return fail("usage: make_mcp_register.py <path-to-workspace-mcp>", code=2)

    binary = Path(argv[1]).resolve()
    if not binary.is_file():
        return fail(f"{binary} is not a file")
    if not os.access(binary, os.X_OK):
        return fail(f"{binary} is not executable")

    if shutil.which("claude") is None:
        return fail("`claude` CLI not found on PATH")

    # Best-effort removal of any existing registration under this name.
    # Non-zero exit just means it wasn't registered, which is fine.
    subprocess.run(
        ["claude", "mcp", "remove", MCP_NAME],
        check=False,
        capture_output=True,
    )

    add_cmd = ["claude", "mcp", "add", MCP_NAME]
    if CLIENT_SECRET_PATH.is_file():
        add_cmd += ["-e", f"GOOGLE_CLIENT_SECRET_PATH={CLIENT_SECRET_PATH}"]
        print(f"  → GOOGLE_CLIENT_SECRET_PATH={CLIENT_SECRET_PATH}")
    else:
        print(
            f"  warning: {CLIENT_SECRET_PATH} not found — workspace-mcp will only "
            "be able to refresh existing tokens, not start new OAuth flows.",
            file=sys.stderr,
        )
    add_cmd += ["--", str(binary), "--tool-tier", TOOL_TIER]

    add = subprocess.run(add_cmd, check=False)
    if add.returncode != 0:
        return fail(f"`claude mcp add {MCP_NAME}` failed", code=add.returncode)

    print(f"Registered {MCP_NAME} -> {binary} --tool-tier {TOOL_TIER}")
    print("Reload Claude Code (restart this session) for the change to take effect.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
