import pytest

from sentinel.config import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Point the audit DB at a temp file and force config defaults for every test."""
    monkeypatch.setenv("SENTINEL_AUDIT_DB", str(tmp_path / "audit.db"))
    monkeypatch.setenv("SENTINEL_CONFIG", str(tmp_path / "absent.yaml"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
