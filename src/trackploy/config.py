"""Configuration discovery and management for trackploy."""

import json
import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field


DEFAULT_REPO_TO_STACK_MAP: dict[str, str] = {}
DEFAULT_SELFHOSTED_ENV_PATH = Path.home() / "deployment" / "selfhosted" / ".env"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "trackploy" / "config.json"


def _parse_env_file(filepath: Path) -> dict[str, str]:
    """Parse a simple .env file into key-value pairs."""
    result = {}
    if not filepath.exists():
        return result
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip().strip("'\"")
    except Exception:
        pass
    return result


class TrackployConfig(BaseModel):
    """Main configuration model for trackploy."""
    dokploy_url: str = "https://dokploy.example.com"
    dokploy_key: str = ""
    github_token: Optional[str] = None
    smee_url: Optional[str] = None
    tracked_repos: list[str] = Field(default_factory=list)
    repo_stack_map: dict[str, str] = Field(default_factory=lambda: DEFAULT_REPO_TO_STACK_MAP.copy())
    active_interval_seconds: float = 10.0
    idle_interval_seconds: float = 25.0
    enable_osc_notifications: bool = True
    enable_desktop_notifications: bool = True
    enable_bell: bool = True
    github_use_cli_first: bool = True
    history_window_hours: float = 2.0

    @classmethod
    def load(
        cls,
        config_path: Optional[Path] = None,
        env_path: Optional[Path] = None,
        dokploy_key: Optional[str] = None,
        dokploy_url: Optional[str] = None,
        smee_url: Optional[str] = None,
        repos: Optional[list[str]] = None,
        history_window_hours: Optional[float] = None,
    ) -> "TrackployConfig":
        """Load configuration hierarchically: Defaults -> .env -> config file -> env vars -> overrides."""
        data: dict[str, Any] = {}

        # 1. Read global config file
        cfg_file = config_path or DEFAULT_CONFIG_PATH
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                    data.update(file_data)
            except Exception:
                pass

        # 2. Read selfhosted / project .env
        target_env = env_path or DEFAULT_SELFHOSTED_ENV_PATH
        env_vars = _parse_env_file(target_env)
        if "DOKPLOY_KEY" in env_vars:
            data["dokploy_key"] = env_vars["DOKPLOY_KEY"]
        elif "DOKPLOY_API_KEY" in env_vars:
            data["dokploy_key"] = env_vars["DOKPLOY_API_KEY"]
        if "DOKPLOY_URL" in env_vars:
            data["dokploy_url"] = env_vars["DOKPLOY_URL"]
        if "SMEE_URL" in env_vars:
            data["smee_url"] = env_vars["SMEE_URL"]

        # 3. Environment variable overrides
        if os.environ.get("DOKPLOY_KEY"):
            data["dokploy_key"] = os.environ["DOKPLOY_KEY"]
        elif os.environ.get("DOKPLOY_API_KEY"):
            data["dokploy_key"] = os.environ["DOKPLOY_API_KEY"]

        if os.environ.get("DOKPLOY_URL"):
            data["dokploy_url"] = os.environ["DOKPLOY_URL"]

        if os.environ.get("SMEE_URL"):
            data["smee_url"] = os.environ["SMEE_URL"]

        if os.environ.get("GITHUB_TOKEN"):
            data["github_token"] = os.environ["GITHUB_TOKEN"]

        # 4. CLI Argument overrides
        if dokploy_key:
            data["dokploy_key"] = dokploy_key
        if dokploy_url:
            data["dokploy_url"] = dokploy_url
        if smee_url:
            data["smee_url"] = smee_url
        if repos:
            data["tracked_repos"] = repos
        if history_window_hours is not None:
            data["history_window_hours"] = history_window_hours

        return cls(**data)
