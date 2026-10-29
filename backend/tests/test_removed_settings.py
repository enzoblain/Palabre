"""A removed setting still present in the environment is reported, never fatal."""

from app.config import removed_settings_present


def test_removed_setting_in_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MCP_SESSION_BINDING", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nMCP_SESSION_BINDING=warn\n")
    assert removed_settings_present(env) == ["MCP_SESSION_BINDING"]


def test_removed_setting_in_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_SESSION_BINDING", "enforce")
    assert removed_settings_present(tmp_path / "missing") == ["MCP_SESSION_BINDING"]


def test_nothing_to_report(tmp_path, monkeypatch):
    monkeypatch.delenv("MCP_SESSION_BINDING", raising=False)
    assert removed_settings_present(tmp_path / "missing") == []
