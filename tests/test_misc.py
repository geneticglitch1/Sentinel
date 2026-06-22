from sentinel.classify import classify_event, service_for
from sentinel.providers.docker_host import build_run_command


def test_build_run_command_renders_spec():
    cmd = build_run_command(
        {
            "image": "postgres:16",
            "name": "pg",
            "memory": "2g",
            "ports": ["5432:5432"],
            "volumes": ["pgdata:/var/lib/postgresql/data"],
            "env": {"POSTGRES_PASSWORD": "secret"},
        }
    )
    assert "docker run -d" in cmd
    assert "--name pg" in cmd
    assert "--restart unless-stopped" in cmd
    assert "--memory 2g" in cmd
    assert "-p 5432:5432" in cmd
    assert "-v pgdata:/var/lib/postgresql/data" in cmd
    assert "-e POSTGRES_PASSWORD=secret" in cmd
    assert cmd.strip().endswith("postgres:16")


def test_build_run_command_requires_image():
    import pytest

    with pytest.raises(ValueError):
        build_run_command({"name": "x"})


def test_service_lookup():
    assert service_for(22) == "SSH"
    assert service_for(5432) == "PostgreSQL"
    assert "1234" in service_for(1234)


def test_classify_wan_block_sensitive_is_high():
    evt = classify_event(
        {"action": "block", "interface": "wan", "proto": "tcp", "src": "9.9.9.9", "dst": "1.1.1.1", "dport": 22}
    )
    assert evt["severity"] == "high"
    assert "SSH" in evt["service"]


def test_classify_https_is_info():
    evt = classify_event(
        {"action": "pass", "interface": "wan", "proto": "tcp", "src": "9.9.9.9", "dst": "1.1.1.1", "dport": 443}
    )
    assert evt["severity"] == "info"
