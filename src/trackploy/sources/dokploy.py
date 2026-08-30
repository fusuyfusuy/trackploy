"""Dokploy API client for managing stacks, deployments, and redeploy triggers."""

from datetime import datetime
from typing import Any, Optional
import httpx
from trackploy.models import ComposeApp, Deployment, DokployStatus


class DokployClient:
    """Client for Dokploy REST API."""

    def __init__(self, base_url: str = "https://dokploy.bogazici.app", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Trackploy/0.1.0",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _parse_status(self, val: Optional[str]) -> DokployStatus:
        if not val:
            return DokployStatus.UNKNOWN
        v = val.lower()
        if v in ("done", "success", "successful"):
            return DokployStatus.DONE
        if v in ("running", "building", "in_progress", "pending"):
            return DokployStatus.RUNNING
        if v in ("error", "failed", "failure"):
            return DokployStatus.ERROR
        if v in ("idle", "none"):
            return DokployStatus.IDLE
        return DokployStatus.UNKNOWN

    def _parse_ts(self, val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None

    def _parse_deployment(self, d: dict[str, Any], compose_id: str, app_name: Optional[str], project_name: Optional[str]) -> Deployment:
        return Deployment(
            deployment_id=str(d.get("deploymentId") or ""),
            compose_id=compose_id,
            app_name=app_name,
            project_name=project_name,
            status=self._parse_status(d.get("status")),
            title=d.get("title"),
            description=d.get("description"),
            created_at=self._parse_ts(d.get("createdAt")),
            started_at=self._parse_ts(d.get("startedAt")),
            finished_at=self._parse_ts(d.get("finishedAt")),
            error_message=d.get("errorMessage"),
            log_path=d.get("logPath"),
        )

    async def get_projects(self) -> list[dict[str, Any]]:
        """Fetch all projects from Dokploy."""
        url = f"{self.base_url}/api/project.all"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=self._headers())
                if res.status_code != 200:
                    return []
                return res.json()
        except Exception:
            return []

    async def get_compose_app(self, compose_id: str) -> Optional[ComposeApp]:
        """Fetch full details for a single compose application."""
        url = f"{self.base_url}/api/compose.one"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=self._headers(), params={"composeId": compose_id})
                if res.status_code != 200:
                    return None
                data = res.json()
                raw_deploys = data.get("deployments", [])
                app_name = data.get("name")
                proj_name = data.get("environment", {}).get("project", {}).get("name") or "unknown"

                parsed_deploys = [
                    self._parse_deployment(d, compose_id, app_name, proj_name)
                    for d in raw_deploys
                ]
                latest_deploy = parsed_deploys[0] if parsed_deploys else None

                return ComposeApp(
                    compose_id=compose_id,
                    name=data.get("name") or "unknown",
                    project_name=proj_name,
                    environment_name=data.get("environment", {}).get("name") or "production",
                    app_name=data.get("appName"),
                    compose_status=self._parse_status(data.get("composeStatus")),
                    compose_type=data.get("composeType"),
                    source_type=data.get("sourceType"),
                    created_at=self._parse_ts(data.get("createdAt")),
                    latest_deployment=latest_deploy,
                    recent_deployments=parsed_deploys[:5],
                )
        except Exception:
            return None

    async def get_all_apps(self, fetch_details: bool = True) -> list[ComposeApp]:
        """Discover and load all compose stacks across all Dokploy projects."""
        projects = await self.get_projects()
        apps: list[ComposeApp] = []

        for proj in projects:
            proj_name = proj.get("name") or "unknown"
            for env in proj.get("environments", []):
                env_name = env.get("name") or "production"
                for comp in env.get("compose", []):
                    comp_id = comp.get("composeId")
                    if not comp_id:
                        continue

                    if fetch_details:
                        details = await self.get_compose_app(comp_id)
                        if details:
                            details.project_name = proj_name
                            details.environment_name = env_name
                            apps.append(details)
                            continue

                    # Light model
                    apps.append(ComposeApp(
                        compose_id=comp_id,
                        name=comp.get("name") or "unknown",
                        project_name=proj_name,
                        environment_name=env_name,
                        app_name=comp.get("appName"),
                        compose_status=self._parse_status(comp.get("composeStatus")),
                    ))

        return apps

    async def trigger_redeploy(self, compose_id: str) -> tuple[bool, str]:
        """Trigger a Dokploy redeployment."""
        url = f"{self.base_url}/api/compose.redeploy"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    url,
                    headers=self._headers(),
                    json={"composeId": compose_id},
                )
                if 200 <= res.status_code < 300:
                    return True, res.text
                return False, f"HTTP {res.status_code}: {res.text}"
        except Exception as e:
            return False, str(e)
