"""Smee.io Server-Sent Events (SSE) client for instant GitHub webhook streaming."""

import asyncio
from datetime import datetime
import json
import logging
from typing import AsyncGenerator, Optional
import httpx
from trackploy.models import (
    CommitEvent,
    EventType,
    TrackployEvent,
    WorkflowConclusion,
    WorkflowRun,
    WorkflowStatus,
)

logger = logging.getLogger("trackploy.smee")


class SmeeClient:
    """Streams real-time GitHub webhook payloads over Smee.io SSE."""

    name = "smee"

    def __init__(self, smee_url: str):
        self.smee_url = smee_url.rstrip("/")

    @staticmethod
    async def create_channel() -> str:
        """Provision a fresh Smee.io webhook channel URL."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://smee.io/new", follow_redirects=False)
                loc = res.headers.get("location")
                if loc:
                    return loc if loc.startswith("http") else f"https://smee.io{loc}"
        except Exception:
            pass
        return "https://smee.io"

    def is_available(self) -> bool:
        """True if a valid HTTP/HTTPS Smee channel URL is provided."""
        return bool(self.smee_url and self.smee_url.startswith("http"))

    @staticmethod
    def parse_webhook_payload(
        event_name: str,
        body: dict,
    ) -> tuple[Optional[CommitEvent], Optional[WorkflowRun], Optional[TrackployEvent]]:
        """Parse raw webhook JSON body into domain objects and events."""
        event_name = (event_name or "").lower()

        # 1. PUSH EVENT
        if event_name == "push":
            # Ignore branch deletions (e.g. 0000000000000000000000000000000000000000)
            if body.get("deleted") is True or body.get("after") == "0000000000000000000000000000000000000000":
                return None, None, None

            repo = body.get("repository", {}).get("full_name") or "unknown"
            ref = body.get("ref", "")
            is_tag = ref.startswith("refs/tags/")
            if is_tag:
                branch = ref.removeprefix("refs/tags/")
            else:
                branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else (ref or "default")

            sender = body.get("sender", {}).get("login") or body.get("pusher", {}).get("name") or "unknown"

            head_commit = body.get("head_commit") or {}
            commits = body.get("commits") or []
            head_sha = (head_commit.get("id") or body.get("after") or body.get("head") or "")[:7]
            prefix = f"Tag {branch}" if is_tag else f"Push to {branch}"
            message = (head_commit.get("message") or (commits[-1].get("message") if commits else prefix)).split("\n")[0]
            author = head_commit.get("author", {}).get("name") or sender
            url = head_commit.get("url") or body.get("compare")

            commit = CommitEvent(
                repo=repo,
                sha=head_sha or "latest",
                branch=branch,
                message=message,
                author=author,
                timestamp=datetime.now(),
                url=url,
            )

            evt_title = f"Tag {branch} pushed to {repo}" if is_tag else f"Push to {repo} ({branch})"
            evt = TrackployEvent(
                event_type=EventType.PUSH,
                source="github",
                target=repo,
                title=evt_title,
                summary=f"[{commit.sha}] {commit.message} by {commit.author}",
                sha=commit.sha,
                branch=branch,
                url=commit.url,
                timestamp=datetime.now(),
            )
            return commit, None, evt

        # 2. WORKFLOW RUN EVENT
        if event_name == "workflow_run":
            wr = body.get("workflow_run") or {}
            repo = body.get("repository", {}).get("full_name") or "unknown"
            status_str = (wr.get("status") or "unknown").lower()
            conclusion_str = (wr.get("conclusion") or "none").lower()

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

            duration = None
            created_at_str = wr.get("created_at")
            updated_at_str = wr.get("updated_at")
            created_at = None
            updated_at = None
            try:
                if created_at_str:
                    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                if updated_at_str:
                    updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                if created_at and updated_at and status == WorkflowStatus.COMPLETED:
                    duration = int((updated_at - created_at).total_seconds())
            except Exception:
                pass

            run = WorkflowRun(
                id=str(wr.get("id") or ""),
                repo=repo,
                name=wr.get("name") or "Workflow",
                workflow_name=wr.get("name") or "Workflow",
                head_branch=wr.get("head_branch") or "default",
                head_sha=str(wr.get("head_sha") or "")[:7],
                event=wr.get("event") or "push",
                status=status,
                conclusion=conclusion,
                created_at=created_at,
                updated_at=updated_at,
                url=wr.get("html_url"),
                display_title=wr.get("display_title") or wr.get("name"),
                run_number=wr.get("run_number"),
                duration_seconds=duration,
            )

            # Determine event type
            if status == WorkflowStatus.QUEUED:
                evt_type = EventType.ACTION_QUEUED
                title = f"Action Queued: {repo}"
            elif status == WorkflowStatus.IN_PROGRESS:
                evt_type = EventType.ACTION_STARTED
                title = f"Action Started: {repo}"
            elif run.is_successful:
                evt_type = EventType.ACTION_COMPLETED
                title = f"Action Succeeded: {repo}"
            elif run.is_failed:
                evt_type = EventType.ACTION_FAILED
                title = f"Action Failed: {repo}"
            elif conclusion == WorkflowConclusion.CANCELLED:
                evt_type = EventType.ACTION_CANCELLED
                title = f"Action Cancelled: {repo}"
            else:
                return None, run, None

            dur_str = f" in {duration}s" if duration else ""
            summary = f"{run.workflow_name} (#{run.run_number or run.id}) on {run.head_branch}{dur_str}: {run.display_title or ''}"

            evt = TrackployEvent(
                event_type=evt_type,
                source="github",
                target=repo,
                title=title,
                summary=summary,
                sha=run.head_sha,
                branch=run.head_branch,
                url=run.url,
                duration_seconds=duration,
                timestamp=datetime.now(),
            )
            return None, run, evt

        return None, None, None

    async def stream_events(self) -> AsyncGenerator[tuple[Optional[CommitEvent], Optional[WorkflowRun], Optional[TrackployEvent]], None]:
        """Connect to Smee.io SSE endpoint and stream parsed webhook events with auto-reconnect."""
        if not self.is_available():
            return

        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }

        backoff = 2.0
        while True:
            try:
                # 60s read timeout acts as a dead-socket watchdog if Smee keepalive pings cease
                timeout = httpx.Timeout(connect=15.0, read=60.0, write=15.0, pool=15.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("GET", self.smee_url, headers=headers) as response:
                        if response.status_code != 200:
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 1.5, 30.0)
                            continue

                        backoff = 2.0  # Reset backoff on successful connection
                        event_type = ""
                        data_lines = []

                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line:
                                # End of SSE frame
                                if data_lines:
                                    raw_data = "\n".join(data_lines)
                                    try:
                                        payload = json.loads(raw_data)
                                        headers_dict = payload.get("headers", {})
                                        gh_event = (
                                            payload.get("x-github-event")
                                            or payload.get("X-GitHub-Event")
                                            or headers_dict.get("x-github-event")
                                            or headers_dict.get("X-GitHub-Event")
                                            or payload.get("event")
                                            or event_type
                                        )
                                        body = payload.get("body") if isinstance(payload.get("body"), dict) else payload

                                        commit, run, evt = self.parse_webhook_payload(gh_event, body)
                                        if commit or run or evt:
                                            yield commit, run, evt
                                    except Exception:
                                        pass
                                    data_lines = []
                                    event_type = ""
                                continue

                            if line.startswith("event:"):
                                event_type = line.removeprefix("event:").strip()
                            elif line.startswith("data:"):
                                data_lines.append(line.removeprefix("data:").strip())

            except (httpx.RequestError, asyncio.CancelledError) as e:
                if isinstance(e, asyncio.CancelledError):
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)
