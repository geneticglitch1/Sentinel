"""MCP server (stdio) exposing Sentinel's tools to Claude Desktop and Claude Code.

Run with ``sentinel mcp`` (or ``python -m sentinel.mcp_server``). Every tool in
``sentinel.tools`` is registered automatically — name, signature, and docstring
become the MCP tool schema, so there is exactly one definition per tool.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import tools


def build_server() -> FastMCP:
    mcp = FastMCP("sentinel")
    for fn in tools.ALL_TOOLS.values():
        mcp.tool()(fn)
    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
