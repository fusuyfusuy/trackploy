"""Core domain models and event representations for trackploy."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WAITING = "waiting"
    REQUESTED = "requested"
    PENDING = "pending"
    UNKNOWN = "unknown"


class WorkflowConclusion(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    NEUTRAL = "neutral"
    STALE = "stale"
    STARTUP_FAILURE = "startup_failure"
    NONE = "none"


class DokployStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    UNKNOWN = "unknown"


class WorkflowRun(BaseModel):
    """Represents a GitHub Actions workflow run."""
    id: str
    repo: str
    name: str
    workflow_name: str
    head_branch: str
    head_sha: str
    event: str
    status: WorkflowStatus
    conclusion: Optional[WorkflowConclusion] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    url: Optional[str] = None
    display_title: Optional[str] = None
    run_number: Optional[int] = None
    duration_seconds: Optional[int] = None

    @property
    def is_active(self) -> bool:
        return self.status in (
            WorkflowStatus.QUEUED,
            WorkflowStatus.IN_PROGRESS,
            WorkflowStatus.WAITING,
            WorkflowStatus.REQUESTED,
            WorkflowStatus.PENDING,
        )

    @property
    def is_successful(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED and self.conclusion == WorkflowConclusion.SUCCESS

    @property
    def is_failed(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED and self.conclusion in (
            WorkflowConclusion.FAILURE,
            WorkflowConclusion.TIMED_OUT,
            WorkflowConclusion.STARTUP_FAILURE,
        )


class CommitEvent(BaseModel):
    """Represents a git push or commit event."""
    repo: str
    sha: str
    branch: str
    message: str
    author: str
    timestamp: Optional[datetime] = None
    url: Optional[str] = None


class Deployment(BaseModel):
    """Represents a deployment record from Dokploy."""
    deployment_id: str
    compose_id: str
    app_name: Optional[str] = None
    project_name: Optional[str] = None
    status: DokployStatus = DokployStatus.UNKNOWN
    title: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    log_path: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.status == DokployStatus.RUNNING

    @property
    def is_successful(self) -> bool:
        return self.status == DokployStatus.DONE

    @property
    def is_failed(self) -> bool:
        return self.status == DokployStatus.ERROR


class ComposeApp(BaseModel):
    """Represents a Dokploy Compose Stack."""
    compose_id: str
    name: str
    project_name: str
    environment_name: str = "production"
    app_name: Optional[str] = None
    compose_status: DokployStatus = DokployStatus.UNKNOWN
    compose_type: Optional[str] = None
    source_type: Optional[str] = None
    created_at: Optional[datetime] = None
    latest_deployment: Optional[Deployment] = None
    recent_deployments: list[Deployment] = Field(default_factory=list)


class EventType(str, Enum):
    PUSH = "PUSH"
    ACTION_QUEUED = "ACTION_QUEUED"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_CANCELLED = "ACTION_CANCELLED"
    DOKPLOY_NUDGE = "DOKPLOY_NUDGE"
    DEPLOY_STARTED = "DEPLOY_STARTED"
    DEPLOY_COMPLETED = "DEPLOY_COMPLETED"
    DEPLOY_FAILED = "DEPLOY_FAILED"


class TrackployEvent(BaseModel):
    """A unified system event emitted by the state machine."""
    event_type: EventType
    source: str  # "github" or "dokploy" or "pipeline"
    target: str  # repo name or app name
    title: str
    summary: str
    timestamp: datetime = Field(default_factory=datetime.now)
    url: Optional[str] = None
    sha: Optional[str] = None
    branch: Optional[str] = None
    duration_seconds: Optional[int] = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_critical(self) -> bool:
        return self.event_type in (
            EventType.ACTION_FAILED,
            EventType.DEPLOY_FAILED,
        )

    @property
    def is_success(self) -> bool:
        return self.event_type in (
            EventType.ACTION_COMPLETED,
            EventType.DEPLOY_COMPLETED,
        )
