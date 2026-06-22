"""Docker host provider (the Debian box, 192.168.1.217).

Driven over SSH as the ``aryan`` user, who is in the ``docker`` group — so no sudo.
Covers container lifecycle, one-sentence deploys (``docker run``), logs, and parsing
Nginx Proxy Manager access logs for per-domain stats.
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any

from .. import ssh
from ..config import Settings, get_settings

_NPM_LINE = re.compile(r"\]\s+(\d{3})\s+-\s+\S+\s+\S+\s+(\S+)\s")


class DockerHostProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cfg = self.settings.docker

    def _ssh(self, command: str) -> str:
        return ssh.run(self.cfg.ssh, command, self.settings).check()

    # --- reads ---------------------------------------------------------------
    def list_containers(self) -> list[dict[str, Any]]:
        raw = self._ssh("docker ps --all --format '{{json .}}'")
        out = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            out.append(
                {
                    "name": d.get("Names"),
                    "image": d.get("Image"),
                    "status": d.get("Status"),
                    "state": d.get("State"),
                    "ports": d.get("Ports"),
                }
            )
        return out

    def logs(self, name: str, tail: int = 200) -> str:
        return self._ssh(f"docker logs --tail {int(tail)} {shlex.quote(name)} 2>&1")

    def npm_domains(self, lines: int = 4000) -> list[dict[str, Any]]:
        glob = f"{self.cfg.npm_logs}/proxy-host-*_access.log"
        raw = self._ssh(f"tail -n {int(lines)} {glob} 2>/dev/null || true")
        stats: dict[str, dict[str, int]] = {}
        for line in raw.splitlines():
            m = _NPM_LINE.search(line)
            if not m:
                continue
            status, host = int(m.group(1)), m.group(2)
            s = stats.setdefault(
                host, {"total": 0, "2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
            )
            s["total"] += 1
            s[f"{status // 100}xx"] = s.get(f"{status // 100}xx", 0) + 1
        return sorted(
            ({"domain": d, **v} for d, v in stats.items()),
            key=lambda r: r["total"],
            reverse=True,
        )

    # --- writes (gated by sentinel.tools) ------------------------------------
    def run_container(self, spec: dict[str, Any]) -> dict[str, Any]:
        cmd = build_run_command(spec)
        cid = self._ssh(cmd).strip()
        return {"container_id": cid[:12], "command": cmd}

    def container_action(self, name: str, action: str) -> dict[str, Any]:
        if action not in {"restart", "stop", "start", "rm"}:
            raise ValueError(f"unsupported container action: {action}")
        flag = "-f" if action == "rm" else ""
        self._ssh(f"docker {action} {flag} {shlex.quote(name)}")
        return {"name": name, "action": action}


def build_run_command(spec: dict[str, Any]) -> str:
    """Render a `docker run -d` command from a deploy spec.

    spec keys: image (required), name, memory ("2g"), cpus, ports (["5432:5432"]),
    volumes (["pgdata:/var/lib/postgresql/data"]), env ({"K":"V"}), restart, command.
    """
    if not spec.get("image"):
        raise ValueError("deploy spec needs an 'image'")
    args: list[str] = ["docker", "run", "-d"]
    if spec.get("name"):
        args += ["--name", shlex.quote(str(spec["name"]))]
    args += ["--restart", shlex.quote(str(spec.get("restart", "unless-stopped")))]
    if spec.get("memory"):
        args += ["--memory", shlex.quote(str(spec["memory"]))]
    if spec.get("cpus"):
        args += ["--cpus", shlex.quote(str(spec["cpus"]))]
    for p in spec.get("ports", []) or []:
        args += ["-p", shlex.quote(str(p))]
    for v in spec.get("volumes", []) or []:
        args += ["-v", shlex.quote(str(v))]
    for k, val in (spec.get("env", {}) or {}).items():
        args += ["-e", shlex.quote(f"{k}={val}")]
    args.append(shlex.quote(str(spec["image"])))
    if spec.get("command"):
        args.append(str(spec["command"]))
    return " ".join(args)
