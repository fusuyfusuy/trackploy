"""Primary GitHub data source using the official `gh` CLI."""

import asyncio
import json
import os
import shutil
from datetime import datetime
from typing import Optional
from trackploy.models import (
    CommitEvent,
    WorkflowConclusion,
    WorkflowRun,
    WorkflowStatus,
)


class GitHubCliClient:
    """Interacts with GitHub via the local `gh` CLI subprocess."""

    name = "github_cli"

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self._gh_path = shutil.which("gh")

    def is_available(self) -> bool:
        """Check if `gh` CLI binary exists."""
        return self._gh_path is not None

    def _get_clean_env(self) -> dict[str, str]:
        """Construct a sanitized environment for `gh` CLI execution."""
        env = os.environ.copy()
        if self.token:
            env["GH_TOKEN"] = self.token
            env["GITHUB_TOKEN"] = self.token
        else:
            # When no explicit token is passed, remove inherited GH_TOKEN/GITHUB_TOKEN
            # so gh CLI automatically uses credentials from ~/.config/gh/hosts.yml
            env.pop("GH_TOKEN", None)
            env.pop("GITHUB_TOKEN", None)
        return env

    async def _run_command(self, args: list[str], timeout: float = 12.0) -> tuple[int, str, str]:
        """Run a `gh` command asynchronously."""
        if not self._gh_path:
            return 1, "", "gh CLI binary not found"

        env = self._get_clean_env()
        # If env token causes auth error, we fall back to unsetting GH_TOKEN/GITHUB_TOKEN
        try:
            proc = await asyncio.create_subprocess_exec(
                self._gh_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            code = proc.returncode or 0
            out = stdout_b.decode("utf-8", errors="replace")
            err = stderr_b.decode("utf-8", errors="replace")

            # If bad credentials error due to invalid token, retry with clean environment (using ~/.config/gh/hosts.yml)
            if code != 0 and any(err_sig in (err + out) for err_sig in ("Bad credentials", "HTTP 401", "invalid", "failed to log in")):
                clean_env = env.copy()
                clean_env.pop("GH_TOKEN", None)
                clean_env.pop("GITHUB_TOKEN", None)
                proc = await asyncio.create_subprocess_exec(
                    self._gh_path,
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=clean_env,
                )
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return proc.returncode or 0, stdout_b.decode("utf-8", errors="replace"), stderr_b.decode("utf-8", errors="replace")

            return code, out, err
        except asyncio.TimeoutError:
            return 1, "", f"gh command timed out after {timeout}s"
        except Exception as e:
            return 1, "", str(e)

    async def get_authenticated_user(self) -> Optional[str]:
        """Fetch current authenticated GitHub login username."""
        code, out, _ = await self._run_command(["api", "user", "--jq", ".login"])
        if code == 0 and out.strip():
            return out.strip()
        return None

    async def get_user_orgs(self) -> list[str]:
        """Fetch organizations the authenticated user belongs to."""
        code, out, _ = await self._run_command(["api", "user/orgs", "--jq", ".[].login"])
        if code == 0 and out.strip():
            return [line.strip() for line in out.splitlines() if line.strip()]
        return []

    async def discover_active_repos(self, limit: int = 15) -> list[str]:
        """Discover actively updated repositories sorted by latest push time."""
        code, out, _ = await self._run_command(["api", f"user/repos?sort=pushed&per_page={limit}", "--jq", ".[].full_name"])
        if code == 0 and out.strip():
            return [line.strip() for line in out.splitlines() if line.strip()]
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
            endpoints.append(f"users/{user}/events?per_page={limit}")
        if orgs:
            for org in orgs:
                endpoints.append(f"orgs/{org}/events?per_page={limit}")

        for ep in endpoints:
            code, out, _ = await self._run_command(["api", ep])
            if code != 0 or not out.strip():
                continue
            try:
                raw_events = json.loads(out)
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
        """Fetch latest workflow runs for a repository."""
        fields = (
            "databaseId,name,workflowName,headBranch,headSha,event,"
            "status,conclusion,createdAt,startedAt,updatedAt,url,displayTitle,number"
        )
        code, out, _ = await self._run_command([
            "run", "list",
            "--repo", repo,
            "--limit", str(limit),
            "--json", fields,
        ])

        if code != 0 or not out.strip():
            return []

        try:
            raw_runs = json.loads(out)
            runs = []
            for r in raw_runs:
                # Parse timestamps
                def _parse_ts(k: str) -> Optional[datetime]:
                    val = r.get(k)
                    if not val:
                        return None
                    try:
                        return datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except Exception:
                        return None

                created_at = _parse_ts("createdAt")
                started_at = _parse_ts("startedAt")
                updated_at = _parse_ts("updatedAt")

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
                    id=str(r.get("databaseId") or ""),
                    repo=repo,
                    name=r.get("name") or r.get("workflowName") or "Workflow",
                    workflow_name=r.get("workflowName") or r.get("name") or "Workflow",
                    head_branch=r.get("headBranch") or "main",
                    head_sha=r.get("headSha") or "",
                    event=r.get("event") or "push",
                    status=status,
                    conclusion=conclusion,
                    created_at=created_at,
                    started_at=started_at,
                    updated_at=updated_at,
                    url=r.get("url"),
                    display_title=r.get("displayTitle"),
                    run_number=r.get("number"),
                    duration_seconds=duration,
                )
                runs.append(run)
            return runs
        except Exception:
            return []

    async def get_latest_commits(self, repo: str, limit: int = 10) -> list[CommitEvent]:
        """Fetch latest commits across all branches using PushEvents and commits fallback."""
        events: list[CommitEvent] = []
        seen_shas: set[str] = set()

        # 1. Query GitHub activity events for PushEvents (multi-branch real-time stream)
        code, out, _ = await self._run_command([
            "api",
            f"repos/{repo}/events?per_page=30",
        ])
        if code == 0 and out.strip():
            try:
                raw_events = json.loads(out)
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
            except Exception:
                pass

        # 2. Fallback to /commits if no PushEvents found (e.g. older repos or initial state)
        if len(events) < limit:
            code_c, out_c, _ = await self._run_command([
                "api",
                f"repos/{repo}/commits?per_page={limit}",
            ])
            if code_c == 0 and out_c.strip():
                try:
                    raw_commits = json.loads(out_c)
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
                except Exception:
                    pass

        return events[:limit]

    async def get_failed_logs(self, repo: str, run_id: str) -> Optional[str]:
        """Retrieve failure logs for a specific run."""
        code, out, _ = await self._run_command([
            "run", "view", run_id,
            "--repo", repo,
            "--log-failed",
        ], timeout=15.0)
        return out if code == 0 and out.strip() else None

    async def list_repo_webhooks(self, repo: str) -> list[dict]:
        """List active webhooks for a repository."""
        code, out, _ = await self._run_command(["api", f"repos/{repo}/hooks"])
        if code == 0 and out.strip():
            try:
                return json.loads(out)
            except Exception:
                pass
        return []

    async def create_repo_webhook(self, repo: str, webhook_url: str) -> tuple[bool, str]:
        """Create a push and workflow_run webhook on a repository."""
        # Check if already exists
        hooks = await self.list_repo_webhooks(repo)
        for h in hooks:
            cfg = h.get("config", {})
            if cfg.get("url", "").rstrip("/") == webhook_url.rstrip("/"):
                return True, "Webhook already registered"

        code, out, err = await self._run_command([
            "api", f"repos/{repo}/hooks",
            "-f", "name=web",
            "-F", "active=true",
            "-F", "events[]=push",
            "-F", "events[]=workflow_run",
            "-f", f"config[url]={webhook_url}",
            "-f", "config[content_type]=json",
        ])
        if code == 0:
            return True, "Webhook successfully created"
        return False, err.strip() or out.strip()
