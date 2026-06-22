"""Thin paramiko wrapper with jump-host (bastion) support.

Used by the OPNsense, Proxmox, and Docker providers to run commands over SSH.
Connections are short-lived: open, run, close — including any jump-host hops.
"""

from __future__ import annotations

from dataclasses import dataclass

import paramiko

from .config import SSHTarget, Settings, get_settings


@dataclass
class CommandResult:
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def check(self) -> str:
        if not self.ok:
            raise SSHCommandError(self.code, self.stderr or self.stdout)
        return self.stdout


class SSHCommandError(RuntimeError):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"remote command failed ({code}): {message.strip()}")


def _open(target: SSHTarget, settings: Settings) -> tuple[paramiko.SSHClient, list[paramiko.SSHClient]]:
    """Open a client to ``target``, returning it plus any jump clients to close later."""
    jumps: list[paramiko.SSHClient] = []
    sock = None
    if target.jump is not None:
        jump_client, jump_chain = _open(target.jump, settings)
        jumps = [*jump_chain, jump_client]
        transport = jump_client.get_transport()
        assert transport is not None
        sock = transport.open_channel(
            "direct-tcpip", (target.host, target.port), ("", 0)
        )

    client = paramiko.SSHClient()
    # Homelab boxes: trust on first use. Set a real known_hosts file in config
    # for production by pre-populating ~/.ssh/known_hosts.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=target.host,
        port=target.port,
        username=target.user,
        key_filename=settings.resolved_key(target),
        sock=sock,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
    )
    return client, jumps


def run(
    target: SSHTarget,
    command: str,
    settings: Settings | None = None,
    timeout: int = 60,
) -> CommandResult:
    """Run a single command on ``target`` and return its result."""
    settings = settings or get_settings()
    client, jumps = _open(target, settings)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        return CommandResult(code=code, stdout=out, stderr=err)
    finally:
        client.close()
        for jc in reversed(jumps):
            jc.close()


def run_sh(target: SSHTarget, command: str, **kw) -> CommandResult:
    """Run a command through ``sh -c`` — OPNsense's root shell is tcsh, so pipelines
    and POSIX syntax need an explicit ``sh`` (a lesson straight from the cowork log)."""
    quoted = command.replace("'", "'\\''")
    return run(target, f"/bin/sh -c '{quoted}'", **kw)
