"""Tests for PollingEngine and end-to-end polling loop."""

from pathlib import Path
import httpx
import pytest
import respx
from trackploy.config import TrackployConfig
from trackploy.core.poller import PollingEngine
from trackploy.models import EventType


@pytest.mark.asyncio
async def test_polling_engine_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DOKPLOY_KEY", raising=False)
    monkeypatch.delenv("DOKPLOY_API_KEY", raising=False)
    monkeypatch.delenv("DOKPLOY_URL", raising=False)

    cfg = TrackployConfig(
        dokploy_key="test-key",
        dokploy_url="https://dokploy.example.com",
        tracked_repos=["fusuycorp/boun-scrape"],
        github_use_cli_first=False,  # Force REST client for mocking in tests
    )

    engine = PollingEngine(cfg)

    with respx.mock(assert_all_called=False) as mock:
        # Dokploy mocks
        mock.get("https://dokploy.example.com/api/project.all").respond(
            status_code=200,
            json=[
                {
                    "name": "boun-uni",
                    "environments": [
                        {
                            "name": "production",
                            "compose": [
                                {"name": "scraper", "composeId": "comp-123", "composeStatus": "done"}
                            ],
                        }
                    ],
                }
            ],
        )
        mock.get("https://dokploy.example.com/api/compose.one").respond(
            status_code=200,
            json={
                "name": "scraper",
                "composeId": "comp-123",
                "composeStatus": "done",
                "environment": {"name": "production", "project": {"name": "boun-uni"}},
                "deployments": [
                    {
                        "deploymentId": "dep-1",
                        "title": "Rebuild deployment",
                        "status": "done",
                        "createdAt": "2026-08-30T12:00:00Z",
                    }
                ],
            },
        )

        # Sequential GitHub Actions responses: Pass 1 (in_progress) -> Pass 2 (completed success)
        resp1 = httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "id": 1001,
                        "name": "Build & Deploy",
                        "head_branch": "main",
                        "head_sha": "abc1234",
                        "event": "push",
                        "status": "in_progress",
                        "conclusion": None,
                        "created_at": "2026-08-30T12:00:00Z",
                    }
                ]
            },
        )
        resp2 = httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "id": 1001,
                        "name": "Build & Deploy",
                        "head_branch": "main",
                        "head_sha": "abc1234",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                        "created_at": "2026-08-30T12:00:00Z",
                        "run_started_at": "2026-08-30T12:00:05Z",
                        "updated_at": "2026-08-30T12:02:05Z",
                    }
                ]
            },
        )

        route_runs = mock.get("https://api.github.com/repos/fusuycorp/boun-scrape/actions/runs")
        route_runs.side_effect = [resp1, resp2]

        mock.get("https://api.github.com/repos/fusuycorp/boun-scrape/commits").respond(
            status_code=200,
            json=[],
        )

        # Pass 1: Baseline initialization
        evts_pass1 = await engine.poll_once()
        assert len(evts_pass1) == 0  # Initial discovery should not flood notifications
        assert engine.state.is_first_run() is False

        # Pass 2: Should emit ACTION_COMPLETED event enriched with Dokploy metadata
        evts_pass2 = await engine.poll_once()
        assert len(evts_pass2) == 1
        evt = evts_pass2[0]
        assert evt.event_type == EventType.ACTION_COMPLETED
        assert evt.target == "fusuycorp/boun-scrape"
        assert evt.duration_seconds == 120
        assert evt.details.get("linked_dokploy_app") == "scraper"
        assert evt.details.get("dokploy_compose_id") == "comp-123"
