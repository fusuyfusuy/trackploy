"""Tests for GitHub and Dokploy data sources."""

import pytest
import respx
import httpx
from trackploy.models import DokployStatus, WorkflowStatus
from trackploy.sources.dokploy import DokployClient
from trackploy.sources.github_api import GitHubApiClient


@pytest.mark.asyncio
async def test_dokploy_client_get_projects():
    with respx.mock(base_url="https://dokploy.bogazici.app") as mock:
        mock.get("/api/project.all").respond(
            status_code=200,
            json=[
                {
                    "name": "boun-uni",
                    "environments": [
                        {
                            "name": "production",
                            "compose": [
                                {"name": "scraper", "composeId": "id-123", "composeStatus": "done"}
                            ],
                        }
                    ],
                }
            ],
        )

        client = DokployClient(api_key="test-key")
        projects = await client.get_projects()
        assert len(projects) == 1
        assert projects[0]["name"] == "boun-uni"


@pytest.mark.asyncio
async def test_dokploy_client_get_compose_app():
    with respx.mock(base_url="https://dokploy.bogazici.app") as mock:
        mock.get("/api/compose.one").respond(
            status_code=200,
            json={
                "name": "scraper",
                "composeId": "id-123",
                "composeStatus": "done",
                "environment": {"name": "production", "project": {"name": "boun-uni"}},
                "deployments": [
                    {
                        "deploymentId": "dep-1",
                        "title": "Rebuild deployment",
                        "status": "done",
                        "createdAt": "2026-08-30T12:00:00Z",
                        "finishedAt": "2026-08-30T12:02:00Z",
                    }
                ],
            },
        )

        client = DokployClient(api_key="test-key")
        app = await client.get_compose_app("id-123")
        assert app is not None
        assert app.name == "scraper"
        assert app.compose_status == DokployStatus.DONE
        assert app.latest_deployment is not None
        assert app.latest_deployment.status == DokployStatus.DONE


@pytest.mark.asyncio
async def test_github_api_client_workflow_runs():
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/fusuycorp/boun-scrape/actions/runs").respond(
            status_code=200,
            json={
                "workflow_runs": [
                    {
                        "id": 999111,
                        "name": "Build & Deploy",
                        "head_branch": "main",
                        "head_sha": "abc1234",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                        "created_at": "2026-08-30T10:00:00Z",
                        "run_started_at": "2026-08-30T10:00:05Z",
                        "updated_at": "2026-08-30T10:02:05Z",
                        "html_url": "https://github.com/fusuycorp/boun-scrape/actions/runs/999111",
                    }
                ]
            },
        )

        client = GitHubApiClient(token="test-token")
        runs = await client.get_workflow_runs("fusuycorp/boun-scrape")
        assert len(runs) == 1
        assert runs[0].id == "999111"
        assert runs[0].status == WorkflowStatus.COMPLETED
        assert runs[0].is_successful is True
        assert runs[0].duration_seconds == 120


@pytest.mark.asyncio
async def test_github_api_client_latest_commits_push_event():
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/fusuycorp/boun-scrape/events").respond(
            status_code=200,
            json=[
                {
                    "type": "PushEvent",
                    "actor": {"login": "octocat"},
                    "payload": {
                        "ref": "refs/heads/feat/crawler-v2",
                        "head": "9988776655",
                        "commits": [
                            {
                                "sha": "998877665544332211",
                                "message": "Add async scraper pipeline",
                                "author": {"name": "Mona Lisa Octocat"},
                            }
                        ],
                    },
                    "created_at": "2026-08-30T15:00:00Z",
                }
            ],
        )

        client = GitHubApiClient(token="test-token")
        commits = await client.get_latest_commits("fusuycorp/boun-scrape")
        assert len(commits) == 1
        assert commits[0].branch == "feat/crawler-v2"
        assert commits[0].sha == "9988776"
        assert commits[0].message == "Add async scraper pipeline"
        assert commits[0].author == "Mona Lisa Octocat"
        assert commits[0].timestamp is not None


@pytest.mark.asyncio
async def test_github_api_client_latest_commits_fallback():
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/fusuycorp/boun-scrape/events").respond(
            status_code=200,
            json=[],  # No events
        )
        mock.get("/repos/fusuycorp/boun-scrape/commits").respond(
            status_code=200,
            json=[
                {
                    "sha": "1122334455",
                    "commit": {
                        "message": "Initial commit",
                        "author": {"name": "Author", "date": "2026-08-30T12:00:00Z"},
                    },
                    "html_url": "https://github.com/fusuycorp/boun-scrape/commit/1122334455",
                }
            ],
        )

        client = GitHubApiClient(token="test-token")
        commits = await client.get_latest_commits("fusuycorp/boun-scrape")
        assert len(commits) == 1
        assert commits[0].sha == "1122334"
        assert commits[0].branch == "default"
        assert commits[0].message == "Initial commit"

