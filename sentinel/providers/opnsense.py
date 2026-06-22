"""OPNsense provider.

Two transports, used where each is reliable:

  * REST API (httpx + key/secret) for config changes — firewall rules, IDS settings.
  * SSH for things the API does not expose cleanly — IDS/CrowdSec status, GeoIP
    lookups, and the raw filter log.

Safety lessons baked in (straight from the cowork log):
  * Back up ``config.xml`` before any mutation.
  * Apply service changes through supported paths only — the REST ``reconfigure``
    endpoints and ``configctl``. **Never** call PHP scripts directly; that is what
    stopped sshd and caused the lockout.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .. import ssh
from ..classify import classify_event
from ..config import Settings, get_settings


class OPNsenseProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cfg = self.settings.opnsense

    # --- transports ----------------------------------------------------------
    def _rest(self, method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
        if not (self.settings.opnsense_api_key and self.settings.opnsense_api_secret):
            raise RuntimeError(
                "OPNsense REST call needs SENTINEL_OPNSENSE_API_KEY/SECRET "
                "(System → Access → Users → API keys)."
            )
        url = f"{self.cfg.base_url.rstrip('/')}{path}"
        auth = httpx.BasicAuth(self.settings.opnsense_api_key, self.settings.opnsense_api_secret)
        with httpx.Client(verify=self.cfg.verify_ssl, timeout=30, auth=auth) as c:
            resp = c.request(method, url, json=payload)
            resp.raise_for_status()
            return resp.json()

    def _ssh(self, command: str) -> str:
        return ssh.run_sh(self.cfg.ssh, command, settings=self.settings).check()

    # --- safety helpers ------------------------------------------------------
    def backup_config(self) -> str:
        ts = time.strftime("%Y%m%d-%H%M%S")
        dest = f"/conf/config.xml.bak-sentinel-{ts}"
        self._ssh(f"cp /conf/config.xml {dest}")
        return dest

    # --- IDS / CrowdSec status ----------------------------------------------
    def ids_status(self, recent: int = 200) -> dict[str, Any]:
        status = self._ssh("configctl ids status").strip()
        events = self._tail_eve(recent)
        drops = sum(1 for e in events if e.get("action") == "drop")
        alerts = sum(1 for e in events if e.get("action") in (None, "allowed"))
        return {
            "service": status,
            "window_events": len(events),
            "drops": drops,
            "alerts_only": alerts,
            "recent": events[:25],
        }

    def _tail_eve(self, n: int) -> list[dict[str, Any]]:
        try:
            raw = self._ssh(f"tail -n {n} /var/log/suricata/eve.json")
        except Exception:
            return []
        out = []
        for line in raw.splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("event_type") != "alert":
                continue
            out.append(
                {
                    "ts": e.get("timestamp"),
                    "src": e.get("src_ip"),
                    "dst": e.get("dest_ip"),
                    "action": (e.get("alert") or {}).get("action"),
                    "signature": (e.get("alert") or {}).get("signature"),
                    "severity": (e.get("alert") or {}).get("severity"),
                }
            )
        return out

    def crowdsec_status(self) -> dict[str, Any]:
        lapi = self._safe("cscli lapi status 2>&1 | head -3").strip()
        decisions_json = self._safe("cscli decisions list -o json 2>/dev/null")
        try:
            decisions = json.loads(decisions_json) if decisions_json.strip() else []
        except Exception:
            decisions = []
        blocklist = self._safe(
            "cscli decisions list -a -o json 2>/dev/null | "
            "python3 -c 'import sys,json;print(len(json.load(sys.stdin) or []))' 2>/dev/null"
        ).strip()
        return {
            "lapi": lapi,
            "local_decisions": len(decisions),
            "blocklist_total": _int(blocklist),
        }

    def _safe(self, command: str) -> str:
        try:
            return self._ssh(command)
        except Exception as exc:  # noqa: BLE001 — status reads should degrade, not crash
            return f"(unavailable: {exc})"

    # --- traffic + GeoIP -----------------------------------------------------
    def firewall_traffic(self, limit: int = 50, classified: bool = True) -> list[dict[str, Any]]:
        raw = self._safe(f"clog {self.cfg.filter_log} 2>/dev/null | tail -n {limit * 3}")
        if raw.startswith("(unavailable"):
            raw = self._safe(f"tail -n {limit * 3} {self.cfg.filter_log}")
        events = []
        for line in raw.splitlines():
            evt = _parse_filter_line(line)
            if evt:
                events.append(classify_event(evt) if classified else evt)
        return events[-limit:][::-1]

    def geo_attackers(self, top: int = 10) -> list[dict[str, Any]]:
        events = self.firewall_traffic(limit=400, classified=False)
        counts: dict[str, int] = {}
        for e in events:
            if e.get("action") == "block" and e.get("src"):
                counts[e["src"]] = counts.get(e["src"], 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top]
        out = []
        for ip, hits in ranked:
            out.append({"ip": ip, "hits": hits, "country": self._geo(ip)})
        return out

    def _geo(self, ip: str) -> str:
        res = self._safe(
            f"mmdblookup --file {self.cfg.geoip_db} --ip {ip} country names en 2>/dev/null"
        )
        for token in res.split('"'):
            if token and token not in {"\n", " "} and "<" not in token and "(" not in token:
                if token.strip() and not token.strip().startswith(("country", "names", "en")):
                    return token.strip()
        return "??"

    # --- writes (gated by sentinel.tools) ------------------------------------
    def firewall_rule(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Add or delete a firewall filter rule via the REST API, then apply.

        Requires the os-firewall plugin / recent core (firewall/filter API).
        """
        self.backup_config()
        if action == "add":
            res = self._rest("POST", "/api/firewall/filter/addRule", {"rule": payload})
        elif action == "delete":
            uuid = payload["uuid"]
            res = self._rest("POST", f"/api/firewall/filter/delRule/{uuid}")
        else:
            raise ValueError(f"unsupported firewall_rule action: {action}")
        apply = self._rest("POST", "/api/firewall/filter/apply")
        return {"action": action, "result": res, "apply": apply}

    def set_ips_mode(self, enabled: bool, block_offenders: bool) -> dict[str, Any]:
        """Enable IPS/inline blocking via the supported REST settings + reconfigure path."""
        self.backup_config()
        current = self._rest("GET", "/api/ids/settings/get")
        general = current.get("ids", {}).get("general", {})
        general["enabled"] = "1" if enabled else "0"
        general["ips"] = "1" if enabled else "0"
        general["blockoffenders"] = "1" if block_offenders else "0"
        setres = self._rest("POST", "/api/ids/settings/set", {"ids": {"general": general}})
        reconf = self._rest("POST", "/api/ids/service/reconfigure")
        return {"set": setres, "reconfigure": reconf}

    def ids_update_rules(self) -> dict[str, Any]:
        out = self._ssh("configctl ids update")
        return {"update": out.strip()[-400:]}


def _int(s: str) -> int:
    try:
        return int(s.strip())
    except Exception:
        return 0


# Filter-log field positions for the common IPv4 TCP/UDP case (OPNsense filterlog CSV).
def _parse_filter_line(line: str) -> dict[str, Any] | None:
    # The CSV is the comma-heavy segment; strip any syslog/filterlog prefix.
    seg = line
    if "filterlog" in line:
        seg = line.split("filterlog", 1)[1].split(": ", 1)[-1]
    parts = seg.split(",")
    if len(parts) < 20:
        return None
    try:
        interface = parts[4]
        action = parts[6]
        direction = parts[7]
        ipversion = parts[8]
        if ipversion != "4":
            return None
        proto = parts[16]
        src = parts[18]
        dst = parts[19]
        dport = int(parts[21]) if len(parts) > 21 and parts[21].isdigit() else None
        return {
            "interface": interface,
            "action": action,
            "direction": direction,
            "proto": proto,
            "src": src,
            "dst": dst,
            "dport": dport,
        }
    except (IndexError, ValueError):
        return None
