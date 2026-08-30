"""Tests for core domain models."""

from datetime import datetime
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


def test_workflow_run_properties():
    active_run = WorkflowRun(
        id="123",
        repo="fusuycorp/boun-scrape",
        name="CI",
        workflow_name="CI",
        head_branch="main",
        head_sha="abcdef123456",
        event="push",
        status=WorkflowStatus.IN_PROGRESS,
    )
    assert active_run.is_active is True
    assert active_run.is_successful is False
    assert active_run.is_failed is False

    success_run = WorkflowRun(
        id="124",
        repo="fusuycorp/boun-scrape",
        name="CI",
        workflow_name="CI",
        head_branch="main",
        head_sha="abcdef123456",
        event="push",
        status=WorkflowStatus.COMPLETED,
        conclusion=WorkflowConclusion.SUCCESS,
    )
    assert success_run.is_active is False
    assert success_run.is_successful is True
    assert success_run.is_failed is False

    failed_run = WorkflowRun(
        id="125",
        repo="fusuycorp/boun-scrape",
        name="CI",
        workflow_name="CI",
        head_branch="main",
        head_sha="abcdef123456",
        event="push",
        status=WorkflowStatus.COMPLETED,
        conclusion=WorkflowConclusion.FAILURE,
    )
    assert failed_run.is_active is False
    assert failed_run.is_successful is False
    assert failed_run.is_failed is True


def test_deployment_properties():
    dep = Deployment(
        deployment_id="dep-1",
        compose_id="comp-1",
        status=DokployStatus.RUNNING,
    )
    assert dep.is_active is True
    assert dep.is_successful is False
    assert dep.is_failed is False

    dep_done = Deployment(
        deployment_id="dep-2",
        compose_id="comp-1",
        status=DokployStatus.DONE,
    )
    assert dep_done.is_successful is True


def test_trackploy_event_properties():
    evt_fail = TrackployEvent(
        event_type=EventType.ACTION_FAILED,
        source="github",
        target="fusuycorp/boun-scrape",
        title="CI Failed",
        summary="Tests failed",
    )
    assert evt_fail.is_critical is True
    assert evt_fail.is_success is False

    evt_success = TrackployEvent(
        event_type=EventType.DEPLOY_COMPLETED,
        source="dokploy",
        target="scraper",
        title="Deployed",
        summary="Service live",
    )
    assert evt_success.is_critical is False
    assert evt_success.is_success is True
