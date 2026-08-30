"""Configuration discovery and management for trackploy."""

import json
import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field


DEFAULT_REPO_TO_STACK_MAP = {
    "boun-scrape": "scraper",
    "fusuycorp/boun-scrape": "scraper",
    "hepyeni": "hepyeni",
    "fusuycorp/hepyeni": "hepyeni",
    "3d-filament-finder": "filament",
    "fusuycorp/3d-filament-finder": "filament",
    "uniyok-atlas": "uni-tercih",
    "fusuycorp/uniyok-atlas": "uni-tercih",
    "yokatlas-scrape": "uni-tercih",
    "fusuycorp/yokatlas-scrape": "uni-tercih",
    "bountools": "bountools",
    "fusuycorp/bountools": "bountools",
    "geriden.com": "geriden-v2-stack",
    "fusuycorp/geriden.com": "geriden-v2-stack",
    "beszel": "beszel-hub",
    "fusuycorp/beszel": "beszel-hub",
    "nextcloud": "nextcloud",
    "umami": "umami",
}

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
    dokploy_url: str = "https://dokploy.bogazici.app"
    dokploy_key: str = ""
    github_token: Optional[str] = None
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
        repos: Optional[list[str]] = None,
        history_window_hours: Optional[float] = None,
    ) -> "TrackployConfig":
        """Load configuration hierarchically: Defaults -> .env -> config file -> env vars -> overrides."""
        data: dict[str, Any] = {}

        # 1. Read selfhosted .env
        target_env = env_path or DEFAULT_SELFHOSTED_ENV_PATH
        env_vars = _parse_env_file(target_env)
        if "DOKPLOY_KEY" in env_vars:
            data["dokploy_key"] = env_vars["DOKPLOY_KEY"]
        elif "DOKPLOY_API_KEY" in env_vars:
            data["dokploy_key"] = env_vars["DOKPLOY_API_KEY"]
        if "DOKPLOY_URL" in env_vars:
            data["dokploy_url"] = env_vars["DOKPLOY_URL"]

        # 2. Read explicit config file
        cfg_file = config_path or DEFAULT_CONFIG_PATH
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                    data.update(file_data)
            except Exception:
                pass

        # 3. Environment variable overrides
        if os.environ.get("DOKPLOY_KEY"):
            data["dokploy_key"] = os.environ["DOKPLOY_KEY"]
        elif os.environ.get("DOKPLOY_API_KEY"):
            data["dokploy_key"] = os.environ["DOKPLOY_API_KEY"]

        if os.environ.get("DOKPLOY_URL"):
            data["dokploy_url"] = os.environ["DOKPLOY_URL"]

        if os.environ.get("GITHUB_TOKEN"):
            data["github_token"] = os.environ["GITHUB_TOKEN"]

        # 4. CLI Argument overrides
        if dokploy_key:
            data["dokploy_key"] = dokploy_key
        if dokploy_url:
            data["dokploy_url"] = dokploy_url
        if repos:
            data["tracked_repos"] = repos
        if history_window_hours is not None:
            data["history_window_hours"] = history_window_hours

        cfg = cls(**data)

        # If no tracked repos were specified, auto-discover from local projects
        if not cfg.tracked_repos:
            cfg.tracked_repos = cls.discover_local_repos()

        return cfg

    @staticmethod
    def discover_local_repos() -> list[str]:
        """Auto-discover local repositories in known workspaces."""
        discovered = []
        base_dirs = [
            Path.home() / "projects" / "fusuycorp",
            Path.home() / "projects" / "fusuyfusuy",
            Path.home() / "projects",
        ]
        seen_names = set()

        for base_dir in base_dirs:
            if not base_dir.exists() or not base_dir.is_dir():
                continue
            for entry in base_dir.iterdir():
                if not entry.is_dir():
                    continue
                name = entry.name
                has_workflows = (entry / ".github" / "workflows").exists()
                is_mapped_stack = name in DEFAULT_REPO_TO_STACK_MAP

                if has_workflows or is_mapped_stack:
                    if base_dir.name in ("fusuycorp", "fusuyfusuy"):
                        repo_slug = f"{base_dir.name}/{name}"
                    else:
                        repo_slug = name

                    if repo_slug not in seen_names and name not in seen_names:
                        seen_names.add(repo_slug)
                        seen_names.add(name)
                        discovered.append(repo_slug)

        # Default fallback list if none discovered
        if not discovered:
            discovered = [
                "fusuycorp/boun-scrape",
                "fusuycorp/hepyeni",
                "fusuycorp/3d-filament-finder",
                "fusuycorp/yokatlas-scrape",
                "fusuycorp/bountools",
                "fusuycorp/geriden.com",
            ]
        return discovered
