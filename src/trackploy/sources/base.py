"""Pluggable boundary interfaces for CI/CD and deployment sources."""

from typing import Any, AsyncGenerator, Optional, Protocol, runtime_checkable
from trackploy.models import CommitEvent, ComposeApp, TrackployEvent, WorkflowRun


@runtime_checkable
class CiSource(Protocol):
    """Protocol for VCS and CI/CD pipelines (GitHub, GitLab, Gitea, Woodpecker)."""
    name: str

    def is_available(self) -> bool:
        """Return True if credentials and tools are available."""
        ...

    async def get_latest_commits(self, target: str, limit: int = 10) -> list[CommitEvent]:
        """Fetch latest commits/pushes for a repository."""
        ...

    async def get_workflow_runs(self, target: str, limit: int = 10) -> list[WorkflowRun]:
        """Fetch latest pipeline/workflow runs."""
        ...

    async def get_failed_logs(self, target: str, run_id: str) -> Optional[str]:
        """Retrieve error logs for a failed run."""
        ...


@runtime_checkable
class DeploySource(Protocol):
    """Protocol for Deployment and Orchestration engines (Dokploy, Coolify, Portainer)."""
    name: str

    def is_available(self) -> bool:
        """Return True if base URL and API key are configured."""
        ...

    async def get_all_apps(self, fetch_details: bool = True) -> list[ComposeApp]:
        """Fetch all managed services/stacks."""
        ...

    async def trigger_redeploy(self, compose_id: str) -> tuple[bool, str]:
        """Trigger redeployment of a service."""
        ...


@runtime_checkable
class EventStreamSource(Protocol):
    """Protocol for real-time event streaming sources (Smee.io SSE, Webhooks)."""
    name: str

    async def stream_events(self) -> AsyncGenerator[TrackployEvent, None]:
        """Stream real-time events as they arrive."""
        ...
