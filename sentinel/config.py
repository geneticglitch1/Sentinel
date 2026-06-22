"""Configuration: non-secret topology in config.yaml, secrets in .env / env vars.

Precedence (highest first): values in config.yaml -> environment (.env) -> defaults.
The defaults below reflect the real homelab so the package is usable with an empty
config as long as the box running it is on the LAN. Override hosts / jump hosts /
ports in config.yaml; never put secrets there.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class SSHTarget(BaseModel):
    """An SSH endpoint, optionally reached through a jump host (bastion)."""

    host: str
    port: int = 22
    user: str = "root"
    key_path: str | None = None  # falls back to Settings.ssh_key_path
    jump: "SSHTarget | None" = None


class ProxmoxConfig(BaseModel):
    api_host: str = "192.168.1.2"
    api_port: int = 8006
    node: str = "pve"
    verify_ssl: bool = False
    # SSH fallback for qm/pct when no API token is configured.
    ssh: SSHTarget = SSHTarget(host="192.168.1.2", port=22, user="root")


class OPNsenseConfig(BaseModel):
    # LAN GUI/API endpoint. From outside the LAN, point this at the WireGuard IP.
    base_url: str = "https://192.168.1.1"
    verify_ssl: bool = False
    # SSH is used for configctl / cscli / suricata / mmdblookup (things the REST
    # API does not expose). On the LAN the firewall listens on :22.
    ssh: SSHTarget = SSHTarget(host="192.168.1.1", port=22, user="root")
    geoip_db: str = "/usr/local/share/GeoIP/GeoLite2-Country.mmdb"
    filter_log: str = "/var/log/filter/latest.log"


class DockerHostConfig(BaseModel):
    ssh: SSHTarget = SSHTarget(host="192.168.1.217", port=22, user="aryan")
    npm_logs: str = "/data/compose/1/data/logs"


class NtfyConfig(BaseModel):
    # Publish straight to the container to dodge the Cloudflare 525 on the
    # public hostname (matches the cowork setup).
    base_url: str = "http://192.168.1.217:8090"
    topic: str = "firewall-alerts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_", env_file=".env", env_nested_delimiter="__", extra="ignore"
    )

    # --- secrets (env / .env only) ---
    anthropic_api_key: str | None = None
    ssh_key_path: str = "~/.ssh/id_ed25519"
    opnsense_api_key: str | None = None
    opnsense_api_secret: str | None = None
    proxmox_token_id: str | None = None  # e.g. "root@pam!sentinel"
    proxmox_token_secret: str | None = None

    # --- behaviour ---
    model: str = "claude-opus-4-8"
    dry_run_default: bool = True
    audit_db: str = "~/.sentinel/audit.db"

    # --- topology (override in config.yaml) ---
    proxmox: ProxmoxConfig = ProxmoxConfig()
    opnsense: OPNsenseConfig = OPNsenseConfig()
    docker: DockerHostConfig = DockerHostConfig()
    ntfy: NtfyConfig = NtfyConfig()

    def resolved_key(self, target: SSHTarget) -> str:
        """Absolute path to the SSH key for a target (falls back to the global key)."""
        return str(Path(target.key_path or self.ssh_key_path).expanduser())


SSHTarget.model_rebuild()


@lru_cache(maxsize=8)
def get_settings(config_path: str | None = None) -> Settings:
    """Load settings, merging config.yaml topology over env-provided secrets."""
    path = Path(config_path or os.environ.get("SENTINEL_CONFIG", "config.yaml")).expanduser()
    data: dict = {}
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
    return Settings(**data)
