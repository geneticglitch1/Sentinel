"""The single source of truth for what Sentinel can do.

Every front-end — the MCP server (Claude Desktop / Claude Code), the Claude Agent
SDK app, and the CLI — calls these functions. Reads return plain data; mutations
return an ``ActionResult`` dict and are wrapped by ``_apply`` which enforces the
dry-run/confirm gate and writes one audit row per call.

Design rule: providers do the I/O, tools own the policy (gate + audit). Nothing
mutates the homelab without going through ``_apply``.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

from . import audit
from .config import Settings, get_settings
from .models import ActionResult, InfraStatus, PlannedChange
from .providers.docker_host import DockerHostProvider, build_run_command
from .providers.opnsense import OPNsenseProvider
from .providers.proxmox import ProxmoxProvider
from .safety import ConfirmationRequired, gate


def _settings() -> Settings:
    return get_settings()


def _proxmox() -> ProxmoxProvider:
    return ProxmoxProvider(_settings())


def _opnsense() -> OPNsenseProvider:
    return OPNsenseProvider(_settings())


def _docker() -> DockerHostProvider:
    return DockerHostProvider(_settings())


def _apply(
    planned: PlannedChange, confirm: bool, do: Callable[[], Any], args: dict[str, Any]
) -> dict[str, Any]:
    """Run a mutation through the safety gate + audit, return an ActionResult dict."""
    try:
        should_apply = gate(planned, confirm)
    except ConfirmationRequired:
        res = ActionResult(
            tool=planned.tool,
            applied=False,
            summary=f"BLOCKED — destructive, pass confirm=true to apply: {planned.summary}",
            planned=planned,
            error="confirmation_required",
        )
        audit.record(res, args)
        return res.model_dump()

    if not should_apply:
        res = ActionResult.dry_run(planned)
        audit.record(res, args)
        return res.model_dump()

    try:
        output = do()
        res = ActionResult(
            tool=planned.tool, applied=True, summary=planned.summary, planned=planned, output=output
        )
    except Exception as exc:  # noqa: BLE001 — surface failures as data, not crashes
        res = ActionResult(
            tool=planned.tool, applied=False, summary=planned.summary, planned=planned, error=str(exc)
        )
    audit.record(res, args)
    return res.model_dump()


# =========================================================================
# Reads
# =========================================================================
def vm_list() -> list[dict[str, Any]]:
    """List Proxmox VMs and containers with status."""
    return _proxmox().list_vms()


def container_list() -> list[dict[str, Any]]:
    """List Docker containers on the docker host."""
    return _docker().list_containers()


def container_logs(name: str, tail: int = 200) -> str:
    """Tail logs for a Docker container."""
    return _docker().logs(name, tail)


def ids_status() -> dict[str, Any]:
    """Suricata IDS/IPS status: service state, recent drops vs alert-only events."""
    return _opnsense().ids_status()


def crowdsec_status() -> dict[str, Any]:
    """CrowdSec LAPI health, local decisions, and blocklist size."""
    return _opnsense().crowdsec_status()


def firewall_traffic(limit: int = 50) -> list[dict[str, Any]]:
    """Recent firewall events, classified into plain English."""
    return _opnsense().firewall_traffic(limit=limit, classified=True)


def geo_attackers(top: int = 10) -> list[dict[str, Any]]:
    """Top blocked source IPs with GeoIP country."""
    return _opnsense().geo_attackers(top=top)


def npm_domains() -> list[dict[str, Any]]:
    """Per-domain request counts + status-code mix from Nginx Proxy Manager logs."""
    return _docker().npm_domains()


def infra_status() -> dict[str, Any]:
    """One snapshot: Proxmox VMs, Docker containers, IDS + CrowdSec."""
    s = InfraStatus()
    try:
        s.proxmox = {"vms": _proxmox().list_vms()}
    except Exception as exc:  # noqa: BLE001
        s.proxmox = {"error": str(exc)}
    try:
        s.docker = {"containers": _docker().list_containers()}
    except Exception as exc:  # noqa: BLE001
        s.docker = {"error": str(exc)}
    try:
        opn = _opnsense()
        s.opnsense = {"ids": opn.ids_status(), "crowdsec": opn.crowdsec_status()}
    except Exception as exc:  # noqa: BLE001
        s.opnsense = {"error": str(exc)}
    return s.model_dump()


def audit_log(limit: int = 50) -> list[dict[str, Any]]:
    """Recent Sentinel actions (planned + applied)."""
    return audit.recent(limit)


# =========================================================================
# Mutations (dry-run by default; destructive ones require confirm=True)
# =========================================================================
def vm_action(vmid: int, action: str, kind: str = "qemu", confirm: bool = False) -> dict[str, Any]:
    """start | stop | reboot | shutdown a Proxmox VM/CT. stop/reboot/shutdown are destructive."""
    destructive = action in {"stop", "reboot", "shutdown"}
    planned = PlannedChange(
        tool="vm_action",
        summary=f"{action} {kind} {vmid}",
        target=f"proxmox:{vmid}",
        destructive=destructive,
        details={"vmid": vmid, "action": action, "kind": kind},
    )
    args = {"vmid": vmid, "action": action, "kind": kind, "confirm": confirm}
    return _apply(planned, confirm, lambda: _proxmox().vm_action(vmid, action, kind), args)


def vm_snapshot(vmid: int, name: str, kind: str = "qemu", confirm: bool = False) -> dict[str, Any]:
    """Snapshot a Proxmox VM/CT."""
    planned = PlannedChange(
        tool="vm_snapshot",
        summary=f"snapshot {kind} {vmid} -> {name}",
        target=f"proxmox:{vmid}",
        details={"vmid": vmid, "name": name, "kind": kind},
    )
    args = {"vmid": vmid, "name": name, "kind": kind, "confirm": confirm}
    return _apply(planned, confirm, lambda: _proxmox().snapshot(vmid, name, kind), args)


def deploy_container(
    image: str,
    name: str | None = None,
    memory: str | None = None,
    cpus: str | None = None,
    ports: list[str] | None = None,
    volumes: list[str] | None = None,
    env: dict[str, str] | None = None,
    restart: str = "unless-stopped",
    command: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Deploy a Docker container on the docker host (the one-sentence-deploy target)."""
    spec = {
        "image": image,
        "name": name,
        "memory": memory,
        "cpus": cpus,
        "ports": ports,
        "volumes": volumes,
        "env": env,
        "restart": restart,
        "command": command,
    }
    rendered = build_run_command(spec)
    planned = PlannedChange(
        tool="deploy_container",
        summary=f"deploy {image}" + (f" as {name}" if name else ""),
        target=f"docker:{name or image}",
        details={"spec": spec, "command": rendered},
    )
    return _apply(planned, confirm, lambda: _docker().run_container(spec), spec)


def container_action(name: str, action: str, confirm: bool = False) -> dict[str, Any]:
    """restart | stop | start | rm a Docker container. stop/rm are destructive."""
    destructive = action in {"stop", "rm"}
    planned = PlannedChange(
        tool="container_action",
        summary=f"{action} container {name}",
        target=f"docker:{name}",
        destructive=destructive,
        details={"name": name, "action": action},
    )
    args = {"name": name, "action": action, "confirm": confirm}
    return _apply(planned, confirm, lambda: _docker().container_action(name, action), args)


def firewall_rule(
    action: str,
    rule: dict[str, Any] | None = None,
    uuid: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Add or delete an OPNsense filter rule (REST + apply). Always destructive.

    Backs up config.xml first. ``add`` takes ``rule`` (filter rule fields);
    ``delete`` takes ``uuid``.
    """
    payload = rule if action == "add" else {"uuid": uuid}
    planned = PlannedChange(
        tool="firewall_rule",
        summary=f"firewall {action} rule",
        target="opnsense:filter",
        destructive=True,
        details={"action": action, "payload": payload},
    )
    args = {"action": action, "rule": rule, "uuid": uuid, "confirm": confirm}
    return _apply(planned, confirm, lambda: _opnsense().firewall_rule(action, payload), args)


def ids_set_mode(
    enabled: bool = True, block_offenders: bool = True, confirm: bool = False
) -> dict[str, Any]:
    """Enable/disable Suricata IPS inline blocking via the supported REST path. Destructive."""
    planned = PlannedChange(
        tool="ids_set_mode",
        summary=f"set IDS enabled={enabled} block_offenders={block_offenders}",
        target="opnsense:ids",
        destructive=True,
        details={"enabled": enabled, "block_offenders": block_offenders},
    )
    args = {"enabled": enabled, "block_offenders": block_offenders, "confirm": confirm}
    return _apply(
        planned, confirm, lambda: _opnsense().set_ips_mode(enabled, block_offenders), args
    )


def ids_update_rules(confirm: bool = False) -> dict[str, Any]:
    """Download/refresh Suricata rulesets (configctl ids update)."""
    planned = PlannedChange(
        tool="ids_update_rules",
        summary="update Suricata rulesets",
        target="opnsense:ids",
        details={},
    )
    return _apply(planned, confirm, lambda: _opnsense().ids_update_rules(), {"confirm": confirm})


def ntfy_alert(message: str, title: str | None = None, priority: str | None = None) -> dict[str, Any]:
    """Publish an alert to the ntfy topic (applied immediately — that's the point)."""
    s = _settings()
    planned = PlannedChange(
        tool="ntfy_alert",
        summary=f"ntfy → {s.ntfy.topic}",
        target=f"ntfy:{s.ntfy.topic}",
        details={"message": message, "title": title},
    )

    def _send() -> dict[str, Any]:
        headers: dict[str, str] = {}
        if title:
            headers["Title"] = title
        if priority:
            headers["Priority"] = priority
        url = f"{s.ntfy.base_url.rstrip('/')}/{s.ntfy.topic}"
        with httpx.Client(timeout=15) as c:
            r = c.post(url, content=message.encode(), headers=headers)
            r.raise_for_status()
        return {"status": "sent", "topic": s.ntfy.topic}

    return _apply(planned, True, _send, {"message": message, "title": title})


# Tool registry consumed by the MCP server and the Agent SDK wrapper.
READ_TOOLS: dict[str, Callable] = {
    "vm_list": vm_list,
    "container_list": container_list,
    "container_logs": container_logs,
    "ids_status": ids_status,
    "crowdsec_status": crowdsec_status,
    "firewall_traffic": firewall_traffic,
    "geo_attackers": geo_attackers,
    "npm_domains": npm_domains,
    "infra_status": infra_status,
    "audit_log": audit_log,
}

WRITE_TOOLS: dict[str, Callable] = {
    "vm_action": vm_action,
    "vm_snapshot": vm_snapshot,
    "deploy_container": deploy_container,
    "container_action": container_action,
    "firewall_rule": firewall_rule,
    "ids_set_mode": ids_set_mode,
    "ids_update_rules": ids_update_rules,
    "ntfy_alert": ntfy_alert,
}

ALL_TOOLS: dict[str, Callable] = {**READ_TOOLS, **WRITE_TOOLS}
