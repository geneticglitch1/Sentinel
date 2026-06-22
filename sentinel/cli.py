"""Sentinel CLI (Typer + rich).

  sentinel deploy "<sentence>"   one-sentence deploy (plan, then confirm)
  sentinel chat                  interactive agent session
  sentinel status                infra snapshot
  sentinel mcp                   run the stdio MCP server (for Claude Desktop/Code)
  sentinel serve                 run the agent + dashboard API (sentinel-agent)
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from . import tools

app = typer.Typer(add_completion=False, help="Claude-driven homelab orchestration.")
console = Console()


def _run_agent(sentence: str, apply: bool) -> None:
    from .agent import run_query

    try:
        result = asyncio.run(run_query(sentence, apply=apply))
    except ImportError:
        console.print(
            "[red]claude-agent-sdk / the `claude` CLI is not installed.[/red] "
            "Install it (npm i -g @anthropic-ai/claude-code; pip install claude-agent-sdk) "
            "or use the MCP server from Claude Desktop/Code instead."
        )
        raise typer.Exit(1)
    if result["tool_calls"]:
        for tc in result["tool_calls"]:
            console.print(f"  [cyan]→ {tc['name']}[/cyan] {tc['input']}")
    console.print(Panel(result["text"] or "(no output)", title="sentinel", border_style="green"))


@app.command()
def deploy(
    sentence: str = typer.Argument(..., help="What to deploy, in one sentence."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without prompting."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only, never apply."),
) -> None:
    """Translate a sentence into a deploy and run it (dry-run first, then confirm)."""
    if yes and not dry_run:
        _run_agent(sentence, apply=True)
        return
    console.print("[dim]Planning (dry run)…[/dim]")
    _run_agent(sentence, apply=False)
    if dry_run:
        return
    if Confirm.ask("Apply this plan?", default=False):
        _run_agent(sentence, apply=True)
    else:
        console.print("[yellow]Aborted — nothing applied.[/yellow]")


@app.command()
def chat(
    apply: bool = typer.Option(False, "--apply", help="Let the agent apply changes this session."),
) -> None:
    """Interactive agent session. Ctrl-D or 'exit' to quit."""
    console.print("[green]Sentinel chat.[/green] Type a request; 'exit' to quit.")
    while True:
        try:
            msg = console.input("[bold cyan]you ›[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            break
        if msg.strip().lower() in {"exit", "quit"}:
            break
        if msg.strip():
            _run_agent(msg, apply=apply)


@app.command()
def status() -> None:
    """Show a snapshot of Proxmox, Docker, and the firewall."""
    snap = tools.infra_status()

    vms = (snap.get("proxmox") or {}).get("vms", [])
    if isinstance(vms, list):
        t = Table(title="Proxmox", show_lines=False)
        for col in ("vmid", "name", "kind", "status"):
            t.add_column(col)
        for v in vms:
            t.add_row(str(v.get("vmid")), str(v.get("name")), str(v.get("kind")), str(v.get("status")))
        console.print(t)
    else:
        console.print(f"[red]Proxmox: {snap.get('proxmox')}[/red]")

    conts = (snap.get("docker") or {}).get("containers", [])
    if isinstance(conts, list):
        t = Table(title="Docker", show_lines=False)
        for col in ("name", "image", "state", "status"):
            t.add_column(col)
        for c in conts:
            t.add_row(str(c.get("name")), str(c.get("image")), str(c.get("state")), str(c.get("status")))
        console.print(t)
    else:
        console.print(f"[red]Docker: {snap.get('docker')}[/red]")

    opn = snap.get("opnsense") or {}
    console.print(Panel(str(opn), title="OPNsense (IDS / CrowdSec)", border_style="blue"))


@app.command()
def mcp() -> None:
    """Run the stdio MCP server (wire into Claude Desktop / Claude Code)."""
    from .mcp_server import main

    main()


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int = typer.Option(8799, help="Port for the agent + dashboard API."),
) -> None:
    """Run the sentinel-agent API (status, audit, deploy/chat) for the dashboard."""
    import uvicorn

    uvicorn.run("sentinel.agent:app", host=host, port=port)


if __name__ == "__main__":
    app()
