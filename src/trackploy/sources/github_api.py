"""Secondary GitHub data source using direct HTTPS REST API calls."""

from datetime import datetime
from typing import Optional
import httpx
from trackploy.models import (
    CommitEvent,
    WorkflowConclusion,
    WorkflowRun,
    WorkflowStatus,
)


class GitHubApiClient:
    """Interacts with GitHub via direct REST API requests."""

    name = "github_api"

    def __init__(self, token: Optional[str] = None, base_url: str = "https://api.github.com"):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def is_available(self) -> bool:
        """True if token is configured or base URL is valid."""
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Trackploy/0.1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def get_authenticated_user(self) -> Optional[str]:
        """Fetch current authenticated GitHub login username."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{self.base_url}/user", headers=self._headers())
                if res.status_code == 200:
                    return res.json().get("login")
        except Exception:
            pass
        return None

    async def get_user_orgs(self) -> list[str]:
        """Fetch organizations the authenticated user belongs to."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{self.base_url}/user/orgs", headers=self._headers())
                if res.status_code == 200:
                    return [item.get("login") for item in res.json() if item.get("login")]
        except Exception:
            pass
        return []

    async def discover_active_repos(self, limit: int = 15) -> list[str]:
        """Discover actively updated repositories sorted by latest push time."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    f"{self.base_url}/user/repos",
                    headers=self._headers(),
                    params={"sort": "pushed", "direction": "desc", "per_page": limit},
                )
                if res.status_code == 200:
                    return [item.get("full_name") for item in res.json() if item.get("full_name")]
        except Exception:
            pass
        return []

    async def get_global_events(
        self,
        user: Optional[str] = None,
        orgs: Optional[list[str]] = None,
        limit: int = 30,
    ) -> list[CommitEvent]:
        """Stream PushEvents from user and organization global activity streams."""
        all_events: list[CommitEvent] = []
        seen_shas: set[str] = set()

        endpoints = []
        if user:
            endpoints.append(f"{self.base_url}/users/{user}/events")
        if orgs:
            for org in orgs:
                endpoints.append(f"{self.base_url}/orgs/{org}/events")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for ep in endpoints:
                    res = await client.get(ep, headers=self._headers(), params={"per_page": limit})
                    if res.status_code != 200:
                        continue
                    raw_events = res.json()
                    for item in raw_events:
                        if item.get("type") != "PushEvent":
                            continue
                        repo = item.get("repo", {}).get("name") or "unknown"
                        payload = item.get("payload", {})
                        ref = payload.get("ref", "")
                        branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else (ref or "default")
                        actor = item.get("actor", {}).get("login", "unknown")
                        ts_str = item.get("created_at")
                        ts = None
                        if ts_str:
                            try:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            except Exception:
                                pass

                        commits = payload.get("commits", [])
                        if commits:
                            for c in reversed(commits):
                                sha = (c.get("sha") or "")[:7]
                                if not sha or sha in seen_shas:
                                    continue
                                seen_shas.add(sha)
                                msg = (c.get("message") or "").split("\n")[0]
                                author = c.get("author", {}).get("name") or actor
                                all_events.append(CommitEvent(
                                    repo=repo,
                                    sha=sha,
                                    branch=branch,
                                    message=msg,
                                    author=author,
                                    timestamp=ts,
                                    url=f"https://github.com/{repo}/commit/{c.get('sha')}" if c.get("sha") else None,
                                ))
                        else:
                            head_sha = (payload.get("head") or "")[:7]
                            if head_sha and head_sha not in seen_shas:
                                seen_shas.add(head_sha)
                                all_events.append(CommitEvent(
                                    repo=repo,
                                    sha=head_sha,
                                    branch=branch,
                                    message=f"Push to {branch}",
                                    author=actor,
                                    timestamp=ts,
                                    url=f"https://github.com/{repo}/commit/{payload.get('head')}" if payload.get("head") else None,
                                ))
        except Exception:
            pass

        return all_events

    async def get_workflow_runs(self, repo: str, limit: int = 5) -> list[WorkflowRun]:
        """Fetch latest workflow runs from GitHub REST API."""
        url = f"{self.base_url}/repos/{repo}/actions/runs"
        params = {"per_page": limit}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=self._headers(), params=params)
                if res.status_code != 200:
                    return []
                data = res.json()
                raw_runs = data.get("workflow_runs", [])
                runs = []
                for r in raw_runs:
                    def _parse_ts(k: str) -> Optional[datetime]:
                        val = r.get(k)
                        if not val:
                            return None
                        try:
                            return datetime.fromisoformat(val.replace("Z", "+00:00"))
                        except Exception:
                            return None

                    created_at = _parse_ts("created_at")
                    started_at = _parse_ts("run_started_at")
                    updated_at = _parse_ts("updated_at")

                    duration = None
                    if started_at and updated_at and r.get("status") == "completed":
                        duration = int((updated_at - started_at).total_seconds())

                    status_str = (r.get("status") or "unknown").lower()
                    conclusion_str = (r.get("conclusion") or "none").lower()

                    status = WorkflowStatus.UNKNOWN
                    for s in WorkflowStatus:
                        if s.value == status_str:
                            status = s
                            break

                    conclusion = None
                    if conclusion_str and conclusion_str != "none":
                        for c in WorkflowConclusion:
                            if c.value == conclusion_str:
                                conclusion = c
                                break

                    run = WorkflowRun(
                        id=str(r.get("id") or ""),
                        repo=repo,
                        name=r.get("name") or "Workflow",
                        workflow_name=r.get("name") or "Workflow",
                        head_branch=r.get("head_branch") or "main",
                        head_sha=r.get("head_sha") or "",
                        event=r.get("event") or "push",
                        status=status,
                        conclusion=conclusion,
                        created_at=created_at,
                        started_at=started_at,
                        updated_at=updated_at,
                        url=r.get("html_url"),
                        display_title=r.get("display_title") or r.get("name"),
                        run_number=r.get("run_number"),
                        duration_seconds=duration,
                    )
                    runs.append(run)
                return runs
        except Exception:
            return []

    async def get_latest_commits(self, repo: str, limit: int = 10) -> list[CommitEvent]:
        """Fetch latest commits from GitHub REST API across all branches."""
        events: list[CommitEvent] = []
        seen_shas: set[str] = set()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. Fetch real-time PushEvents from repository event stream
                events_url = f"{self.base_url}/repos/{repo}/events"
                res_events = await client.get(events_url, headers=self._headers(), params={"per_page": 30})
                if res_events.status_code == 200:
                    raw_events = res_events.json()
                    for item in raw_events:
                        if item.get("type") != "PushEvent":
                            continue
                        payload = item.get("payload", {})
                        ref = payload.get("ref", "")
                        branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else (ref or "default")
                        actor = item.get("actor", {}).get("login", "unknown")
                        ts_str = item.get("created_at")
                        ts = None
                        if ts_str:
                            try:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            except Exception:
                                pass

                        commits = payload.get("commits", [])
                        if commits:
                            for c in reversed(commits):
                                sha = (c.get("sha") or "")[:7]
                                if not sha or sha in seen_shas:
                                    continue
                                seen_shas.add(sha)
                                msg = (c.get("message") or "").split("\n")[0]
                                author = c.get("author", {}).get("name") or actor
                                events.append(CommitEvent(
                                    repo=repo,
                                    sha=sha,
                                    branch=branch,
                                    message=msg,
                                    author=author,
                                    timestamp=ts,
                                    url=f"https://github.com/{repo}/commit/{c.get('sha')}" if c.get("sha") else None,
                                ))
                        else:
                            head_sha = (payload.get("head") or "")[:7]
                            if head_sha and head_sha not in seen_shas:
                                seen_shas.add(head_sha)
                                events.append(CommitEvent(
                                    repo=repo,
                                    sha=head_sha,
                                    branch=branch,
                                    message=f"Push to {branch}",
                                    author=actor,
                                    timestamp=ts,
                                    url=f"https://github.com/{repo}/commit/{payload.get('head')}" if payload.get("head") else None,
                                ))

                # 2. Fallback to /commits if no PushEvents found
                if len(events) < limit:
                    commits_url = f"{self.base_url}/repos/{repo}/commits"
                    res_commits = await client.get(commits_url, headers=self._headers(), params={"per_page": limit})
                    if res_commits.status_code == 200:
                        raw_commits = res_commits.json()
                        for c in raw_commits:
                            sha = (c.get("sha") or "")[:7]
                            if not sha or sha in seen_shas:
                                continue
                            seen_shas.add(sha)
                            commit_info = c.get("commit", {})
                            message = commit_info.get("message", "").split("\n")[0]
                            author_info = commit_info.get("author", {})
                            author = author_info.get("name") or c.get("author", {}).get("login", "unknown")
                            ts_str = author_info.get("date")
                            ts = None
                            if ts_str:
                                try:
                                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                except Exception:
                                    pass
                            events.append(CommitEvent(
                                repo=repo,
                                sha=sha,
                                branch="default",
                                message=message,
                                author=author,
                                timestamp=ts,
                                url=c.get("html_url"),
                            ))

                return events[:limit]
        except Exception:
            return events[:limit]

    async def get_failed_logs(self, repo: str, run_id: str) -> Optional[str]:
        """Fetch failed workflow logs from GitHub REST API."""
        url = f"{self.base_url}/repos/{repo}/actions/runs/{run_id}/logs"
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                res = await client.get(url, headers=self._headers())
                if res.status_code == 200:
                    return res.text
        except Exception:
            pass
        return None
