"""
Vercel function - the MCP endpoint.
GET lists the tool catalog; POST speaks JSON-RPC 2.0 (streamable HTTP), the
transport MCP clients use. Handlers live in api/_mcp.py and call the same
engines as the UI, so the agent surface and the app cannot drift.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

# Vercel's Python builder finds a function by STATICALLY looking for a `handler`
# class statement. It does not follow `handler = make_handler(...)`, so every
# shim in this repo was invisible to it: the build reported "pattern does not
# match any Serverless Functions", produced a static-only site, and production
# silently kept serving an old deploy. Subclassing keeps the one-line shim while
# giving the builder the class statement it needs.
_Base = make_handler("mcp")


class handler(_Base):
    pass