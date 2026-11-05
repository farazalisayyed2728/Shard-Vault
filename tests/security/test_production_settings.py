import importlib


def test_vercel_runtime_host_is_used_when_allowed_hosts_is_unset(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "")
    monkeypatch.setenv("VERCEL_URL", "shard-vault-preview.vercel.app")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "")
    monkeypatch.setenv("SECRET_KEY", "s" * 50)
    monkeypatch.setenv("HMAC_SECRET", "h" * 32)
    monkeypatch.setenv("FILE_ENCRYPTION_KEY", "f" * 32)

    production_settings = importlib.import_module("config.settings.prod")

    assert "shard-vault-preview.vercel.app" in production_settings.ALLOWED_HOSTS
