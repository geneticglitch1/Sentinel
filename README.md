# Sentinel

I got tired of SSHing through three different boxes every time I wanted to do one small
thing in my homelab. Spin up a container? That's a hop to the Docker host. Open a port for
it? Now I'm in the OPNsense GUI hunting for the filter rules. Check whether the firewall is
actually dropping the scans hitting it, or just politely logging them? Different tab,
different login.

Sentinel is me handing all of that to Claude. I describe what I want in a sentence, it
figures out the tool calls, shows me the plan, and — only if I say so — does it.

It talks to three things:

- **Proxmox** — my VM/CT host (`192.168.1.2`)
- **OPNsense** — the firewall (`192.168.1.1`), running Suricata IPS + CrowdSec
- **A Docker host** — the Debian box (`192.168.1.217`) where most of my containers live

And it's reachable three ways, all sharing the same tools:

- as an **MCP server** I add to **Claude Desktop**
- as a **Claude Code plugin** (`/mcp` → `sentinel`)
- as a standalone **Claude Agent SDK** app — that's what powers `sentinel deploy "…"` and
  the dashboard

## The one rule: dry-run by default

Everything that changes something is a dry run unless I pass `confirm=true`. And anything
genuinely destructive — stop a VM, delete a firewall rule, `rm` a container, flip IDS mode —
flat-out refuses to run without the confirm. It doesn't "probably" apply. It returns the
plan and stops.

I'm strict about this for a dumb reason: while building the security stack by hand, I
managed to stop sshd on the firewall mid-change and lock myself out. Recoverable (LAN GUI
saved me), but never again. So the OPNsense provider here only ever changes things through
supported paths — `configctl`, the REST `reconfigure` endpoints — never a raw PHP call, and
it backs up `config.xml` before it touches anything. The lockout is baked into the design as
a thing that can't happen the same way twice.

## What it can do

**Infra** — list/start/stop/reboot/snapshot Proxmox VMs, list/deploy/restart/remove Docker
containers, add/remove OPNsense firewall rules.

**Security** — Suricata IPS status (drops vs. alert-only), CrowdSec health + blocklist size,
top attacker IPs with GeoIP country, a human-readable feed of what's hitting the firewall
right now, per-domain request stats from Nginx Proxy Manager, and ntfy alerts.

Every single call — planned or applied — gets written to an audit log the dashboard reads.

## One-sentence deploy

```bash
sentinel deploy "run postgres:16 on the docker host, 2GB RAM, expose 5432, volume pgdata"
```

It plans first (shows you the actual `docker run` it would execute), then asks before
applying. `-y` to skip the prompt, `--dry-run` to never apply.

## Setup

You'll need `uv` (or pip) and an SSH key that can reach the boxes. On the LAN, the defaults
in `config.example.yaml` already point at the right places.

```bash
uv sync
cp config.example.yaml config.yaml      # edit hosts if your network differs
cp .env.example .env                     # add ANTHROPIC_API_KEY, point at your SSH key
```

Sanity check (read-only, safe):

```bash
uv run sentinel status
```

### Wire it into Claude Desktop

Add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sentinel": {
      "command": "sentinel",
      "args": ["mcp"],
      "env": { "SENTINEL_CONFIG": "/absolute/path/to/Sentinel/config.yaml" }
    }
  }
}
```

(If `sentinel` isn't on your PATH, use the full path to the `uv`-installed script, or
`uv run --directory /path/to/Sentinel sentinel mcp`.)

### Wire it into Claude Code

The `plugin/` folder is a ready-made plugin — it ships `.mcp.json` pointing at
`sentinel mcp`. Load it, then `/mcp` should show `sentinel` and the tools.

### The agent + dashboard (on the Docker host)

The one-sentence-deploy agent and the dashboard backend run as a container on `.217`:

```bash
docker compose up -d sentinel-agent
```

The dashboard itself extends my existing **secdash** Next.js app rather than replacing it —
see [`dashboard/README.md`](dashboard/README.md) for the three new panels (Deploy console,
Infra, Audit log) and how to drop them into the app you've already got on `:8095`.

## How it's put together

There's exactly one definition of each tool, in `sentinel/tools.py`. The MCP server, the
Agent SDK app, and the CLI all import the same functions — so there's no "the deploy works
in Claude Desktop but not from the CLI" drift. Providers (`sentinel/providers/`) do the raw
I/O and stay honest about side effects; the tool layer owns the dry-run/confirm gate and the
audit log. That split is the whole reason the safety story holds together.

```
sentinel/
  tools.py          # the one source of truth (gate + audit wrap the providers)
  safety.py         # dry-run / confirm gate
  audit.py          # sqlite audit log
  providers/        # proxmox / opnsense / docker_host
  mcp_server.py     # FastMCP stdio  (Claude Desktop / Claude Code)
  agent.py          # Claude Agent SDK + FastAPI  (deploy/chat/dashboard)
  cli.py            # deploy / chat / status / mcp / serve
```

## Things that will bite you

- **The agent needs the `claude` CLI.** `claude-agent-sdk` drives it under the hood. The MCP
  server and `sentinel status` don't need it — only `deploy`/`chat`/`serve` do. The Docker
  image installs it for you.
- **Off the LAN?** The firewall is bound to LAN/WireGuard only (good), so from outside you
  either connect over WireGuard or set a `jump:` host in `config.yaml` to hop through
  Proxmox. The defaults assume you're on the LAN.
- **OPNsense REST bits** (firewall rules, IDS mode changes) need an API key/secret. The
  status reads (IDS/CrowdSec/GeoIP/traffic) only need SSH and work without it.
- **Proxmox without a token** falls back to `qm`/`pct` over SSH — fine, but the SSH user
  needs to be able to run them (i.e. root).
- **Host keys** are trust-on-first-use for homelab convenience. If you care, pre-populate
  `known_hosts` and tighten `sentinel/ssh.py`.

## License

MIT.
