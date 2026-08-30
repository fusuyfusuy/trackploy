"""Async polling orchestrator for GitHub and Dokploy sources."""

import asyncio
from datetime import datetime
from typing import AsyncGenerator, Optional
from trackploy.config import TrackployConfig
from trackploy.core.correlator import PipelineCorrelator
from trackploy.core.state import StateManager
from trackploy.models import CommitEvent, ComposeApp, TrackployEvent, WorkflowRun
from trackploy.sources.dokploy import DokployClient
from trackploy.sources.github_api import GitHubApiClient
from trackploy.sources.github_cli import GitHubCliClient


class PollingEngine:
    """Orchestrates async polling of GitHub actions and Dokploy deployments."""

    def __init__(self, config: TrackployConfig):
        self.config = config
        self.state = StateManager()
        self.correlator = PipelineCorrelator(config.repo_stack_map)

        self.gh_cli = GitHubCliClient(token=config.github_token)
        self.gh_api = GitHubApiClient(token=config.github_token)
        self.dokploy = DokployClient(
            base_url=config.dokploy_url,
            api_key=config.dokploy_key,
        )

        self._cached_apps: list[ComposeApp] = []
        self._cached_runs: dict[str, list[WorkflowRun]] = {}
        self._cached_commits: dict[str, list[CommitEvent]] = {}

    @property
    def latest_apps(self) -> list[ComposeApp]:
        return self._cached_apps

    @property
    def latest_runs(self) -> dict[str, list[WorkflowRun]]:
        return self._cached_runs

    @property
    def latest_commits(self) -> dict[str, list[CommitEvent]]:
        return self._cached_commits

    async def _fetch_repo_runs(self, repo: str) -> list[WorkflowRun]:
        """Fetch workflow runs using `gh` CLI first, falling back to REST API."""
        if self.config.github_use_cli_first and self.gh_cli.is_available():
            runs = await self.gh_cli.get_workflow_runs(repo, limit=10)
            if runs:
                return runs

        # Fallback to direct REST API
        return await self.gh_api.get_workflow_runs(repo, limit=10)

    async def _fetch_repo_commits(self, repo: str) -> list[CommitEvent]:
        """Fetch latest commits using `gh` CLI first, falling back to REST API."""
        if self.config.github_use_cli_first and self.gh_cli.is_available():
            commits = await self.gh_cli.get_latest_commits(repo, limit=10)
            if commits:
                return commits

        return await self.gh_api.get_latest_commits(repo, limit=10)

    async def poll_once(self) -> list[TrackployEvent]:
        """Perform a single round of polling across GitHub and Dokploy."""
        events: list[TrackployEvent] = []

        # 1. Poll Dokploy
        if self.config.dokploy_key:
            try:
                apps = await self.dokploy.get_all_apps(fetch_details=True)
                self._cached_apps = apps
                for app in apps:
                    if app.latest_deployment:
                        evt = self.state.process_deployment(app.latest_deployment, app.name)
                        if evt:
                            events.append(evt)
            except Exception:
                pass

        # 2. Poll GitHub Repositories concurrently
        async def _check_repo(repo: str) -> list[TrackployEvent]:
            repo_events: list[TrackployEvent] = []
            try:
                runs = await self._fetch_repo_runs(repo)
                self._cached_runs[repo] = runs
                for run in runs:
                    evt = self.state.process_workflow_run(run)
                    if evt:
                        repo_events.append(evt)

                commits = await self._fetch_repo_commits(repo)
                self._cached_commits[repo] = list(commits)
                for c in commits:
                    evt = self.state.process_commit(c)
                    if evt:
                        repo_events.append(evt)

                # Ensure push events from workflow runs are also captured if events stream missed them
                for run in runs:
                    if run.event == "push" and run.head_sha:
                        c_from_run = CommitEvent(
                            repo=repo,
                            sha=run.head_sha[:7],
                            branch=run.head_branch or "default",
                            message=run.display_title or f"Push to {run.head_branch}",
                            author="github",
                            timestamp=run.created_at or datetime.now(),
                            url=run.url,
                        )
                        evt_c = self.state.process_commit(c_from_run)
                        if evt_c:
                            repo_events.append(evt_c)
                        # Add to cached commits if SHA not present
                        if not any(c.sha == c_from_run.sha for c in self._cached_commits[repo]):
                            self._cached_commits[repo].append(c_from_run)
            except Exception:
                pass
            return repo_events

        repo_tasks = [_check_repo(r) for r in self.config.tracked_repos]
        if repo_tasks:
            results = await asyncio.gather(*repo_tasks)
            for r_evts in results:
                events.extend(r_evts)

        # Mark initialized after first full pass so initial discovery doesn't flood notifications
        if self.state.is_first_run():
            self.state.mark_initialized()
            return []

        # Enrich events with cross-correlation data
        enriched_events = [self.correlator.enrich_event(e, self._cached_apps) for e in events]
        return enriched_events

    def has_active_operations(self) -> bool:
        """Check if any CI run or deployment is actively in-flight."""
        for runs in self._cached_runs.values():
            if any(r.is_active for r in runs):
                return True
        for app in self._cached_apps:
            if app.latest_deployment and app.latest_deployment.is_active:
                return True
            if app.compose_status.value == "running":
                return True
        return False

    async def run_loop(self) -> AsyncGenerator[list[TrackployEvent], None]:
        """Continuous polling generator yielding events as they occur."""
        while True:
            events = await self.poll_once()
            if events:
                yield events

            # Dynamic sleep interval based on activity
            interval = (
                self.config.active_interval_seconds
                if self.has_active_operations()
                else self.config.idle_interval_seconds
            )
            await asyncio.sleep(interval)
