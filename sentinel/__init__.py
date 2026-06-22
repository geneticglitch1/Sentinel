"""Sentinel — Claude-driven homelab orchestration.

One tool layer (`sentinel.tools`) drives Proxmox, OPNsense, and a Docker host.
It is exposed three ways: an MCP server (Claude Desktop / Claude Code), a
Claude Agent SDK app (one-sentence deploys + dashboard backend), and a CLI.
"""

__version__ = "0.1.0"
