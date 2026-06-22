from sentinel import audit, tools


class FakeDocker:
    def __init__(self):
        self.calls = []

    def run_container(self, spec):
        self.calls.append(("run", spec))
        return {"container_id": "abc123", "command": "docker run -d ..."}

    def container_action(self, name, action):
        self.calls.append((action, name))
        return {"name": name, "action": action}


def _patch_docker(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setattr(tools, "_docker", lambda: fake)
    return fake


def test_deploy_dry_run_touches_nothing(monkeypatch):
    fake = _patch_docker(monkeypatch)
    res = tools.deploy_container(image="postgres:16", name="pg", ports=["5432:5432"])
    assert res["applied"] is False
    assert "DRY-RUN" in res["summary"]
    assert fake.calls == []  # nothing executed
    rows = audit.recent(5)
    assert rows and rows[0]["tool"] == "deploy_container" and rows[0]["applied"] is False


def test_deploy_apply_runs_once_and_audits(monkeypatch):
    fake = _patch_docker(monkeypatch)
    res = tools.deploy_container(image="postgres:16", name="pg", confirm=True)
    assert res["applied"] is True
    assert len(fake.calls) == 1 and fake.calls[0][0] == "run"
    assert audit.recent(1)[0]["applied"] is True


def test_destructive_blocked_without_confirm(monkeypatch):
    fake = _patch_docker(monkeypatch)
    res = tools.container_action("pg", "stop")
    assert res["applied"] is False
    assert res["error"] == "confirmation_required"
    assert fake.calls == []  # refused, nothing ran


def test_destructive_runs_with_confirm(monkeypatch):
    fake = _patch_docker(monkeypatch)
    res = tools.container_action("pg", "stop", confirm=True)
    assert res["applied"] is True
    assert fake.calls == [("stop", "pg")]


def test_planned_change_marks_destructive(monkeypatch):
    _patch_docker(monkeypatch)
    res = tools.container_action("pg", "rm")  # destructive
    assert res["planned"]["destructive"] is True
