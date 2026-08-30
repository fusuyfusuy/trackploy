"""State tracking and event transition detection."""

from datetime import datetime
from typing import Optional
from trackploy.models import (
    CommitEvent,
    ComposeApp,
    Deployment,
    DokployStatus,
    EventType,
    TrackployEvent,
    WorkflowConclusion,
    WorkflowRun,
    WorkflowStatus,
)


class StateManager:
    """Tracks previous observation states to detect transitions and emit events."""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._runs: dict[str, WorkflowRun] = {}  # key: f"{repo}:{run_id}"
        self._commits: dict[str, CommitEvent] = {}  # key: f"{repo}:{sha}"
        self._deployments: dict[str, Deployment] = {}  # key: f"{compose_id}:{deployment_id}"
        self._emitted_event_keys: set[str] = set()
        self._is_initialized = False

    def is_first_run(self) -> bool:
        """True if the state manager has not completed its first ingest cycle."""
        return not self._is_initialized

    def mark_initialized(self) -> None:
        """Mark initial snapshot complete so future changes emit transition events."""
        self._is_initialized = True

    def process_commit(self, commit: CommitEvent) -> Optional[TrackployEvent]:
        """Process a commit event and return an event if newly observed."""
        key = f"{commit.repo}:{commit.sha}"
        if key in self._commits:
            return None

        self._commits[key] = commit
        if not self._is_initialized:
            return None

        evt_key = f"PUSH:{key}"
        if evt_key in self._emitted_event_keys:
            return None
        self._emitted_event_keys.add(evt_key)

        return TrackployEvent(
            event_type=EventType.PUSH,
            source="github",
            target=commit.repo,
            title=f"Push to {commit.repo} ({commit.branch})",
            summary=f"[{commit.sha}] {commit.message} by {commit.author}",
            sha=commit.sha,
            branch=commit.branch,
            url=commit.url,
            timestamp=commit.timestamp or datetime.now(),
        )

    def process_workflow_run(self, run: WorkflowRun) -> Optional[TrackployEvent]:
        """Process a workflow run and return a transition event if state changed."""
        key = f"{run.repo}:{run.id}"
        prev = self._runs.get(key)
        self._runs[key] = run

        if not self._is_initialized:
            return None

        # Check for transitions
        if prev is None:
            # First time seeing this run
            if run.status == WorkflowStatus.QUEUED:
                evt_type = EventType.ACTION_QUEUED
                title = f"Action Queued: {run.repo}"
            elif run.status == WorkflowStatus.IN_PROGRESS:
                evt_type = EventType.ACTION_STARTED
                title = f"Action Started: {run.repo}"
            elif run.is_successful:
                evt_type = EventType.ACTION_COMPLETED
                title = f"Action Succeeded: {run.repo}"
            elif run.is_failed:
                evt_type = EventType.ACTION_FAILED
                title = f"Action Failed: {run.repo}"
            else:
                return None
        else:
            # State transition
            if prev.status != run.status or prev.conclusion != run.conclusion:
                if run.status == WorkflowStatus.IN_PROGRESS and prev.status != WorkflowStatus.IN_PROGRESS:
                    evt_type = EventType.ACTION_STARTED
                    title = f"Action In-Progress: {run.repo}"
                elif run.is_successful:
                    evt_type = EventType.ACTION_COMPLETED
                    title = f"Action Succeeded: {run.repo}"
                elif run.is_failed:
                    evt_type = EventType.ACTION_FAILED
                    title = f"Action Failed: {run.repo}"
                elif run.conclusion == WorkflowConclusion.CANCELLED:
                    evt_type = EventType.ACTION_CANCELLED
                    title = f"Action Cancelled: {run.repo}"
                else:
                    return None
            else:
                return None

        evt_key = f"{evt_type.value}:{key}:{run.status.value}:{run.conclusion.value if run.conclusion else 'none'}"
        if evt_key in self._emitted_event_keys:
            return None
        self._emitted_event_keys.add(evt_key)

        duration_str = f" in {run.duration_seconds}s" if run.duration_seconds else ""
        summary = f"{run.workflow_name} (#{run.run_number or run.id}) on {run.head_branch}{duration_str}: {run.display_title or ''}"

        return TrackployEvent(
            event_type=evt_type,
            source="github",
            target=run.repo,
            title=title,
            summary=summary,
            sha=run.head_sha[:7] if run.head_sha else None,
            branch=run.head_branch,
            url=run.url,
            duration_seconds=run.duration_seconds,
            timestamp=run.updated_at or datetime.now(),
            details={"run_id": run.id, "workflow": run.workflow_name, "conclusion": str(run.conclusion)},
        )

    def process_deployment(self, deploy: Deployment, app_name: str) -> Optional[TrackployEvent]:
        """Process a Dokploy deployment and return a transition event if state changed."""
        key = f"{deploy.compose_id}:{deploy.deployment_id}"
        prev = self._deployments.get(key)
        self._deployments[key] = deploy

        if not self._is_initialized:
            return None

        target_name = app_name or deploy.app_name or deploy.compose_id

        if prev is None:
            # Newly observed deployment
            if deploy.status == DokployStatus.RUNNING:
                evt_type = EventType.DEPLOY_STARTED
                title = f"Dokploy Deploying: {target_name}"
            elif deploy.status == DokployStatus.DONE:
                evt_type = EventType.DEPLOY_COMPLETED
                title = f"Dokploy Deployed: {target_name}"
            elif deploy.status == DokployStatus.ERROR:
                evt_type = EventType.DEPLOY_FAILED
                title = f"Dokploy Deploy Failed: {target_name}"
            else:
                return None
        else:
            if prev.status != deploy.status:
                if deploy.status == DokployStatus.RUNNING:
                    evt_type = EventType.DEPLOY_STARTED
                    title = f"Dokploy Deploying: {target_name}"
                elif deploy.status == DokployStatus.DONE:
                    evt_type = EventType.DEPLOY_COMPLETED
                    title = f"Dokploy Deployed: {target_name}"
                elif deploy.status == DokployStatus.ERROR:
                    evt_type = EventType.DEPLOY_FAILED
                    title = f"Dokploy Deploy Failed: {target_name}"
                else:
                    return None
            else:
                return None

        evt_key = f"{evt_type.value}:{key}:{deploy.status.value}"
        if evt_key in self._emitted_event_keys:
            return None
        self._emitted_event_keys.add(evt_key)

        summary = f"[{deploy.title or 'Deployment'}] Status: {deploy.status.value.upper()}"
        if deploy.error_message:
            summary += f" - Error: {deploy.error_message}"

        return TrackployEvent(
            event_type=evt_type,
            source="dokploy",
            target=target_name,
            title=title,
            summary=summary,
            timestamp=deploy.finished_at or deploy.started_at or datetime.now(),
            details={
                "compose_id": deploy.compose_id,
                "deployment_id": deploy.deployment_id,
                "error": deploy.error_message,
            },
        )
