"""Proxmox VE provider.

Primary path: the Proxmox API via ``proxmoxer`` + an API token (set
SENTINEL_PROXMOX_TOKEN_ID / SENTINEL_PROXMOX_TOKEN_SECRET). Fallback: ``qm`` / ``pct``
over SSH when no token is configured. The fallback matches how the cowork session
drove the box (root over SSH through the LAN jump host).
"""

from __future__ import annotations

import json
from typing import Any

from .. import ssh
from ..config import Settings, get_settings


class ProxmoxProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cfg = self.settings.proxmox

    # --- transport selection -------------------------------------------------
    @property
    def _has_token(self) -> bool:
        return bool(self.settings.proxmox_token_id and self.settings.proxmox_token_secret)

    def _api(self):
        from proxmoxer import ProxmoxAPI

        user_realm, token_name = self.settings.proxmox_token_id.split("!", 1)
        return ProxmoxAPI(
            self.cfg.api_host,
            port=self.cfg.api_port,
            user=user_realm,
            token_name=token_name,
            token_value=self.settings.proxmox_token_secret,
            verify_ssl=self.cfg.verify_ssl,
        )

    def _ssh(self, command: str) -> str:
        return ssh.run(self.cfg.ssh, command, self.settings).check()

    # --- reads ---------------------------------------------------------------
    def list_vms(self) -> list[dict[str, Any]]:
        if self._has_token:
            api = self._api()
            node = self.cfg.node
            vms = [
                {**v, "kind": "qemu"} for v in api.nodes(node).qemu.get()
            ] + [
                {**c, "kind": "lxc"} for c in api.nodes(node).lxc.get()
            ]
            return [
                {
                    "vmid": v.get("vmid"),
                    "name": v.get("name"),
                    "status": v.get("status"),
                    "kind": v["kind"],
                    "cpu": v.get("cpu"),
                    "mem": v.get("mem"),
                    "maxmem": v.get("maxmem"),
                }
                for v in vms
            ]
        return self._list_vms_ssh()

    def _list_vms_ssh(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for kind, cmd in (("qemu", "qm list"), ("lxc", "pct list")):
            text = self._ssh(cmd)
            lines = [ln for ln in text.splitlines() if ln.strip()][1:]  # drop header
            for ln in lines:
                parts = ln.split()
                if len(parts) >= 3:
                    out.append(
                        {
                            "vmid": int(parts[0]),
                            "name": parts[2] if kind == "qemu" else parts[-1],
                            "status": parts[2] if kind == "lxc" else parts[1],
                            "kind": kind,
                        }
                    )
        return out

    def node_status(self) -> dict[str, Any]:
        if self._has_token:
            return dict(self._api().nodes(self.cfg.node).status.get())
        # uptime + load as a lightweight stand-in over SSH
        up = self._ssh("uptime").strip()
        return {"node": self.cfg.node, "uptime": up}

    # --- writes (callers gate these via sentinel.tools) ----------------------
    def vm_action(self, vmid: int, action: str, kind: str = "qemu") -> dict[str, Any]:
        if action not in {"start", "stop", "reboot", "shutdown"}:
            raise ValueError(f"unsupported vm action: {action}")
        if self._has_token:
            api = self._api()
            res = getattr(getattr(api.nodes(self.cfg.node), kind)(vmid).status, action).post()
            return {"vmid": vmid, "action": action, "task": res}
        cli = "qm" if kind == "qemu" else "pct"
        self._ssh(f"{cli} {action} {vmid}")
        return {"vmid": vmid, "action": action, "via": "ssh"}

    def snapshot(self, vmid: int, name: str, kind: str = "qemu") -> dict[str, Any]:
        if self._has_token:
            api = self._api()
            getattr(api.nodes(self.cfg.node), kind)(vmid).snapshot.post(snapname=name)
            return {"vmid": vmid, "snapshot": name}
        cli = "qm" if kind == "qemu" else "pct"
        self._ssh(f"{cli} snapshot {vmid} {name}")
        return {"vmid": vmid, "snapshot": name, "via": "ssh"}
