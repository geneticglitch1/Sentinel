from sentinel.providers.opnsense import OPNsenseProvider, _parse_filter_line


def test_firewall_rule_backs_up_and_uses_rest_not_php(monkeypatch):
    p = OPNsenseProvider()
    ssh_cmds = []
    rest_calls = []
    monkeypatch.setattr(p, "_ssh", lambda cmd: ssh_cmds.append(cmd) or "")
    monkeypatch.setattr(
        p, "_rest", lambda m, path, payload=None: rest_calls.append((m, path)) or {"ok": True}
    )

    p.firewall_rule("add", {"description": "allow pg"})

    # config.xml backed up before the mutation (cowork lesson #3)
    assert any("config.xml.bak-sentinel" in c for c in ssh_cmds)
    # change + apply went through the supported REST path
    assert ("POST", "/api/firewall/filter/addRule") in rest_calls
    assert ("POST", "/api/firewall/filter/apply") in rest_calls
    # never a raw PHP call (cowork lesson #1 — that's what caused the lockout)
    assert not any("php" in c.lower() for c in ssh_cmds)


def test_set_ips_mode_uses_reconfigure(monkeypatch):
    p = OPNsenseProvider()
    monkeypatch.setattr(p, "_ssh", lambda cmd: "")
    calls = []

    def fake_rest(method, path, payload=None):
        calls.append((method, path))
        if path == "/api/ids/settings/get":
            return {"ids": {"general": {}}}
        return {"ok": True}

    monkeypatch.setattr(p, "_rest", fake_rest)
    p.set_ips_mode(enabled=True, block_offenders=True)
    assert ("POST", "/api/ids/service/reconfigure") in calls  # supported apply path


def test_parse_filter_line_ipv4_tcp():
    fields = [
        "5", "0", "", "label", "wan", "match", "block", "in", "4", "0x0", "",
        "64", "12345", "0", "none", "6", "tcp", "60", "1.2.3.4", "5.6.7.8", "44321", "22",
    ]
    evt = _parse_filter_line("filterlog: " + ",".join(fields))
    assert evt is not None
    assert evt["action"] == "block"
    assert evt["interface"] == "wan"
    assert evt["dport"] == 22
    assert evt["src"] == "1.2.3.4"


def test_parse_filter_line_rejects_garbage():
    assert _parse_filter_line("not a filter line") is None
