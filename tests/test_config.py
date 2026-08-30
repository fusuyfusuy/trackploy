"""Tests for configuration loading and discovery."""

import json
from pathlib import Path
import pytest
from trackploy.config import TrackployConfig, _parse_env_file


def test_parse_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("""
# Comment line
DOKPLOY_KEY=secret-token-123
DOKPLOY_URL=https://custom-dokploy.domain.com
EMPTY_VAL=
""", encoding="utf-8")

    parsed = _parse_env_file(env_file)
    assert parsed["DOKPLOY_KEY"] == "secret-token-123"
    assert parsed["DOKPLOY_URL"] == "https://custom-dokploy.domain.com"
    assert parsed["EMPTY_VAL"] == ""


def test_config_load_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DOKPLOY_URL", raising=False)
    monkeypatch.delenv("DOKPLOY_KEY", raising=False)
    monkeypatch.delenv("DOKPLOY_API_KEY", raising=False)

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "dokploy_url": "https://config-file.domain.com",
        "active_interval_seconds": 5.0,
    }), encoding="utf-8")

    cfg = TrackployConfig.load(
        config_path=cfg_file,
        env_path=tmp_path / "dummy.env",
        dokploy_key="cli-key",
        repos=["fusuycorp/test-repo"],
        history_window_hours=4.5,
    )

    assert cfg.dokploy_key == "cli-key"
    assert cfg.dokploy_url == "https://config-file.domain.com"
    assert cfg.active_interval_seconds == 5.0
    assert cfg.tracked_repos == ["fusuycorp/test-repo"]
    assert cfg.history_window_hours == 4.5
