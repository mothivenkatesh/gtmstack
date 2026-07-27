#!/usr/bin/env python3
"""
GTMstack MCP server, stdio transport.

A thin shim over api/_mcp.py: read one JSON-RPC message per line on stdin,
write one response per line on stdout. Same handlers as the HTTP endpoint, so
there is exactly one implementation of the tool surface.

Wire it into a client (Claude Desktop, Cursor) with:

    {
      "mcpServers": {
        "gtmstack": {
          "command": "/absolute/path/to/gtmforce/.venv/bin/python",
          "args": ["/absolute/path/to/gtmforce/mcp_server.py"]
        }
      }
    }

Nothing is printed to stdout except protocol messages: stdio transport treats
stray output as a framing error, so logs go to stderr.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))

from _mcp import handle  # noqa: E402


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
