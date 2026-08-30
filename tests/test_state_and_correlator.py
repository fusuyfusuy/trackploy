"""Tests for StateManager and PipelineCorrelator."""

from datetime import datetime
from trackploy.core.correlator import PipelineCorrelator
from trackploy.core.state import StateManager
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


def test_state_manager_transitions():
    state = StateManager()

    run_v1 = WorkflowRun(
        id="run-1",
        repo="fusuycorp/boun-scrape",
        name="CI",
        workflow_name="CI",
        head_branch="main",
        head_sha="sha1",
        event="push",
        status=WorkflowStatus.IN_PROGRESS,
    )

    # Initial snapshot pass should not emit events
    evt = state.process_workflow_run(run_v1)
    assert evt is None
    assert state.is_first_run() is True

    # Mark initialized
    state.mark_initialized()
    assert state.is_first_run() is False

    # Status transition to completed
    run_v2 = WorkflowRun(
        id="run-1",
        repo="fusuycorp/boun-scrape",
        name="CI",
        workflow_name="CI",
        head_branch="main",
        head_sha="sha1",
        event="push",
        status=WorkflowStatus.COMPLETED,
        conclusion=WorkflowConclusion.SUCCESS,
        duration_seconds=65,
    )

    evt = state.process_workflow_run(run_v2)
    assert evt is not None
    assert evt.event_type == EventType.ACTION_COMPLETED
    assert evt.target == "fusuycorp/boun-scrape"
    assert evt.duration_seconds == 65

    # Same status repeated should not emit duplicate event
    evt_dup = state.process_workflow_run(run_v2)
    assert evt_dup is None


def test_state_manager_deployment_transitions():
    state = StateManager()
    state.mark_initialized()

    dep_running = Deployment(
        deployment_id="dep-1",
        compose_id="comp-scraper",
        status=DokployStatus.RUNNING,
        title="Rebuild deployment",
    )

    evt1 = state.process_deployment(dep_running, app_name="scraper")
    assert evt1 is not None
    assert evt1.event_type == EventType.DEPLOY_STARTED
    assert evt1.target == "scraper"

    dep_done = Deployment(
        deployment_id="dep-1",
        compose_id="comp-scraper",
        status=DokployStatus.DONE,
        title="Rebuild deployment",
    )

    evt2 = state.process_deployment(dep_done, app_name="scraper")
    assert evt2 is not None
    assert evt2.event_type == EventType.DEPLOY_COMPLETED
    assert evt2.target == "scraper"


def test_pipeline_correlator():
    mapping = {
        "fusuycorp/boun-scrape": "scraper",
        "fusuycorp/hepyeni": "hepyeni",
    }
    correlator = PipelineCorrelator(mapping)

    apps = [
        ComposeApp(
            compose_id="comp-1",
            name="scraper",
            project_name="boun-uni",
            compose_status=DokployStatus.DONE,
        ),
        ComposeApp(
            compose_id="comp-2",
            name="hepyeni",
            project_name="publicality",
            compose_status=DokployStatus.DONE,
        ),
    ]

    matched = correlator.match_app_for_repo("fusuycorp/boun-scrape", apps)
    assert matched is not None
    assert matched.compose_id == "comp-1"

    evt = TrackployEvent(
        event_type=EventType.ACTION_COMPLETED,
        source="github",
        target="fusuycorp/boun-scrape",
        title="Success",
        summary="Done",
    )

    enriched = correlator.enrich_event(evt, apps)
    assert enriched.details.get("linked_dokploy_app") == "scraper"
    assert enriched.details.get("dokploy_compose_id") == "comp-1"


def test_state_manager_commit_transitions():
    state = StateManager()
    c1 = CommitEvent(
        repo="fusuycorp/boun-scrape",
        sha="abc1234",
        branch="feat/parser",
        message="Add resilient parser",
        author="devhax",
    )

    # Initial cycle stores baseline
    assert state.process_commit(c1) is None
    state.mark_initialized()

    # Duplicate commit returns None
    assert state.process_commit(c1) is None

    # New feature branch push emits PUSH event with correct branch
    c2 = CommitEvent(
        repo="fusuycorp/boun-scrape",
        sha="def5678",
        branch="feat/parser",
        message="Add integration tests",
        author="devhax",
    )
    evt = state.process_commit(c2)
    assert evt is not None
    assert evt.event_type == EventType.PUSH
    assert evt.branch == "feat/parser"
    assert evt.sha == "def5678"
    assert "feat/parser" in evt.title


def test_console_notifier_status_table():
    from trackploy.notifiers.console import ConsoleNotifier
    from rich.console import Console
    import io

    buf = io.StringIO()
    test_console = Console(file=buf, force_terminal=False, color_system=None)
    notifier = ConsoleNotifier(console=test_console)

    commits = {
        "fusuycorp/boun-scrape": [
            CommitEvent(
                repo="fusuycorp/boun-scrape",
                sha="abc1234",
                branch="feat/parser",
                message="Add parser",
                author="devhax",
                timestamp=datetime.now(),
            )
        ]
    }
    runs = {
        "fusuycorp/boun-scrape": [
            WorkflowRun(
                id="101",
                repo="fusuycorp/boun-scrape",
                name="CI",
                workflow_name="CI",
                head_branch="feat/parser",
                head_sha="abc1234",
                event="push",
                status=WorkflowStatus.COMPLETED,
                conclusion=WorkflowConclusion.SUCCESS,
                updated_at=datetime.now(),
            )
        ]
    }
    apps = [
        ComposeApp(
            compose_id="comp-1",
            name="scraper",
            project_name="boun-uni",
            compose_status=DokployStatus.DONE,
        )
    ]

    notifier.render_status_table(runs=runs, apps=apps, commits=commits, since_hours=2.0)
    output = buf.getvalue()
    assert "Recent Git Pushes (Last 2h)" in output
    assert "feat/parser" in output
    assert "abc1234" in output
    assert "CI/CD (Last 2h)" in output
    assert "Dokploy Swarm Stacks" in output


def test_pipeline_correlator_dynamic_matching():
    # Empty static mapping -> matches dynamically based on normalized tokens
    correlator = PipelineCorrelator({})
    apps = [
        ComposeApp(
            compose_id="comp-takecare",
            name="takecare",
            project_name="health",
            compose_status=DokployStatus.DONE,
        ),
        ComposeApp(
            compose_id="comp-filament",
            name="filament-finder",
            project_name="tools",
            compose_status=DokployStatus.DONE,
        ),
    ]

    # Exact name match
    m1 = correlator.match_app_for_repo("fusuycorp/takecare", apps)
    assert m1 is not None
    assert m1.compose_id == "comp-takecare"

    # Token overlap match ("3d-filament-finder" matches "filament-finder")
    m2 = correlator.match_app_for_repo("fusuycorp/3d-filament-finder", apps)
    assert m2 is not None
    assert m2.compose_id == "comp-filament"


