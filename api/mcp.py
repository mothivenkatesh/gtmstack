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

handler = make_handler("mcp")
