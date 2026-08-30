"""Async polling orchestrator for GitHub, Dokploy, and Smee.io event streams."""

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
from trackploy.sources.smee import SmeeClient


class PollingEngine:
    """Orchestrates async polling of GitHub actions, Dokploy deployments, and Smee webhooks."""

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
        self.smee = SmeeClient(config.smee_url) if config.smee_url else None

        self._cached_apps: list[ComposeApp] = []
        self._cached_runs: dict[str, list[WorkflowRun]] = {}
        self._cached_commits: dict[str, list[CommitEvent]] = {}

        self._github_user: Optional[str] = None
        self._github_orgs: list[str] = []
        self._discovered_active_repos: set[str] = set(config.tracked_repos)

    @property
    def latest_apps(self) -> list[ComposeApp]:
        return self._cached_apps

    @property
    def latest_runs(self) -> dict[str, list[WorkflowRun]]:
        return self._cached_runs

    @property
    def latest_commits(self) -> dict[str, list[CommitEvent]]:
        return self._cached_commits

    async def _ensure_github_context(self) -> None:
        """Discover authenticated username and member organizations once."""
        if self._github_user is not None:
            return

        active_client = self.gh_cli if (self.config.github_use_cli_first and self.gh_cli.is_available()) else self.gh_api
        try:
            user = await active_client.get_authenticated_user()
            if user:
                self._github_user = user
            orgs = await active_client.get_user_orgs()
            if orgs:
                self._github_orgs = orgs
        except Exception:
            pass

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
        """Perform a single round of polling across Dokploy and dynamic GitHub streams."""
        events: list[TrackployEvent] = []

        # 1. Poll Dokploy Stacks
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

        # 2. Ingest Account & Org Global Event Streams (Zero Hardcoding)
        await self._ensure_github_context()
        active_gh = self.gh_cli if (self.config.github_use_cli_first and self.gh_cli.is_available()) else self.gh_api

        try:
            global_commits = await active_gh.get_global_events(
                user=self._github_user,
                orgs=self._github_orgs,
                limit=30,
            )
            for c in global_commits:
                self._discovered_active_repos.add(c.repo)
                self._cached_commits.setdefault(c.repo, [])
                if not any(existing.sha == c.sha for existing in self._cached_commits[c.repo]):
                    self._cached_commits[c.repo].insert(0, c)
                evt = self.state.process_commit(c)
                if evt:
                    events.append(evt)
        except Exception:
            pass

        # 3. Discover Active Repositories for CI Runs
        try:
            pushed_repos = await active_gh.discover_active_repos(limit=10)
            for r in pushed_repos:
                self._discovered_active_repos.add(r)
        except Exception:
            pass

        # Merge statically tracked repos with dynamically discovered active repos
        repos_to_check = set(self.config.tracked_repos) | set(self._discovered_active_repos)

        async def _check_repo(repo: str) -> list[TrackployEvent]:
            repo_events: list[TrackployEvent] = []
            try:
                runs = await self._fetch_repo_runs(repo)
                self._cached_runs[repo] = runs
                for run in runs:
                    evt = self.state.process_workflow_run(run)
                    if evt:
                        repo_events.append(evt)

                # Fallback commit check if repo has no global events cached
                if repo not in self._cached_commits or not self._cached_commits[repo]:
                    commits = await self._fetch_repo_commits(repo)
                    self._cached_commits[repo] = list(commits)
                    for c in commits:
                        evt = self.state.process_commit(c)
                        if evt:
                            repo_events.append(evt)

                # Ensure push events from workflow runs are captured
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
                        if not any(c.sha == c_from_run.sha for c in self._cached_commits.get(repo, [])):
                            self._cached_commits.setdefault(repo, []).append(c_from_run)
            except Exception:
                pass
            return repo_events

        if repos_to_check:
            results = await asyncio.gather(*[_check_repo(r) for r in repos_to_check])
            for r_evts in results:
                events.extend(r_evts)

        # Mark initialized after first full pass
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
        """Continuous generator yielding real-time webhook and polling events."""
        event_queue: asyncio.Queue[TrackployEvent] = asyncio.Queue()

        # Background Smee.io SSE Webhook Task
        async def _smee_worker():
            if not self.smee or not self.smee.is_available():
                return
            try:
                async for commit, run, evt in self.smee.stream_events():
                    if commit:
                        self._cached_commits.setdefault(commit.repo, []).insert(0, commit)
                        push_evt = self.state.process_commit(commit)
                        if push_evt:
                            enriched = self.correlator.enrich_event(push_evt, self._cached_apps)
                            await event_queue.put(enriched)
                    if run:
                        self._cached_runs.setdefault(run.repo, []).insert(0, run)
                        run_evt = self.state.process_workflow_run(run)
                        if run_evt:
                            enriched = self.correlator.enrich_event(run_evt, self._cached_apps)
                            await event_queue.put(enriched)
                    elif evt and not commit and not run:
                        enriched = self.correlator.enrich_event(evt, self._cached_apps)
                        await event_queue.put(enriched)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        smee_task = asyncio.create_task(_smee_worker())

        try:
            while True:
                # 1. Drain any instant events from Smee queue
                immediate_events: list[TrackployEvent] = []
                while not event_queue.empty():
                    immediate_events.append(event_queue.get_nowait())

                if immediate_events:
                    yield immediate_events

                # 2. Run periodic polling sweep
                polled_events = await self.poll_once()
                if polled_events:
                    yield polled_events

                # 3. Dynamic sleep interval
                interval = (
                    self.config.active_interval_seconds
                    if self.has_active_operations()
                    else self.config.idle_interval_seconds
                )
                try:
                    # Wait for interval OR instant Smee event wakeup
                    instant_evt = await asyncio.wait_for(event_queue.get(), timeout=interval)
                    yield [instant_evt]
                except asyncio.TimeoutError:
                    pass
        finally:
            smee_task.cancel()
            await asyncio.gather(smee_task, return_exceptions=True)
