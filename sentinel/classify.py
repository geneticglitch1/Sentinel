"""Turn raw firewall events into human-readable English.

Promoted from the secdash dashboard's classifier so the same logic is available
as a tool (firewall_traffic) and on the dashboard.
"""

from __future__ import annotations

# port -> (service, is_sensitive). Sensitive ports hitting the WAN are worth flagging.
PORT_SERVICES: dict[int, str] = {
    22: "SSH",
    2223: "SSH (alt)",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    443: "HTTPS",
    445: "SMB",
    1433: "MSSQL",
    3306: "MySQL",
    3389: "RDP",
    5060: "SIP/VoIP",
    5432: "PostgreSQL",
    5900: "VNC",
    6379: "Redis",
    8080: "HTTP-alt",
    8443: "HTTPS-alt",
    9443: "OPNsense GUI",
    2375: "Docker API",
    2376: "Docker API (TLS)",
    27017: "MongoDB",
    51820: "WireGuard",
}


def service_for(port: int | None) -> str:
    if port is None:
        return "unknown"
    return PORT_SERVICES.get(port, f"port {port}")


def classify_event(evt: dict) -> dict:
    """Given a parsed filter-log row, attach a human-readable summary + severity.

    Expected keys (best-effort): action (pass/block), interface, proto,
    src, dst, dport (int), direction.
    """
    action = (evt.get("action") or "").lower()
    iface = (evt.get("interface") or "").lower()
    dport = evt.get("dport")
    svc = service_for(dport)
    is_wan = iface in {"wan", "igb0", "em0", "vtnet0"} or evt.get("zone") == "wan"

    if action == "block":
        if is_wan and dport in PORT_SERVICES:
            sev, text = "high", f"Blocked inbound {svc} probe from {evt.get('src')}"
        elif is_wan:
            sev, text = "medium", f"Blocked inbound scan → {svc} from {evt.get('src')}"
        else:
            sev, text = "low", f"Blocked {svc} ({evt.get('src')} → {evt.get('dst')})"
    elif evt.get("proto") == "udp" and dport == 51820:
        sev, text = "info", f"WireGuard VPN handshake from {evt.get('src')}"
    elif dport == 443:
        sev, text = "info", f"HTTPS request → NPM (proxied site) from {evt.get('src')}"
    elif action == "pass":
        sev, text = "info", f"Allowed {svc} ({evt.get('src')} → {evt.get('dst')})"
    else:
        sev, text = "low", f"{action or 'event'} {svc} from {evt.get('src')}"

    return {**evt, "service": svc, "severity": sev, "summary": text}
