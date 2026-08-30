"""Rich console renderer for events, logs, and status dashboards."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from trackploy.models import (
    CommitEvent,
    ComposeApp,
    DokployStatus,
    EventType,
    TrackployEvent,
    WorkflowConclusion,
    WorkflowRun,
    WorkflowStatus,
)


class ConsoleNotifier:
    """Renders formatted events and status tables to the terminal."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def _event_badge(self, evt: TrackployEvent) -> Text:
        badges = {
            EventType.PUSH: Text(" 📦 PUSH ", style="bold black on cyan"),
            EventType.ACTION_QUEUED: Text(" ⏳ QUEUED ", style="bold black on yellow"),
            EventType.ACTION_STARTED: Text(" ⚙️ RUNNING ", style="bold black on blue"),
            EventType.ACTION_COMPLETED: Text(" ✓ SUCCESS ", style="bold white on green"),
            EventType.ACTION_FAILED: Text(" ✗ FAILED ", style="bold white on red"),
            EventType.ACTION_CANCELLED: Text(" ⊘ CANCEL ", style="bold white on magenta"),
            EventType.DOKPLOY_NUDGE: Text(" 📡 NUDGE ", style="bold black on yellow"),
            EventType.DEPLOY_STARTED: Text(" 🚀 DEPLOYING ", style="bold white on blue"),
            EventType.DEPLOY_COMPLETED: Text(" 🌟 DEPLOYED ", style="bold white on green"),
            EventType.DEPLOY_FAILED: Text(" 💥 DEPLOY FAIL ", style="bold white on red"),
        }
        return badges.get(evt.event_type, Text(f" {evt.event_type.value} ", style="bold"))

    def render_event(self, event: TrackployEvent) -> None:
        """Print a single formatted notification event line to the console."""
        ts = event.timestamp.strftime("%H:%M:%S")
        badge = self._event_badge(event)

        target_text = Text(f"[{event.target}]", style="bold bright_white")
        title_text = Text(f" {event.title}", style="bold")
        summary_text = Text(f"\n  ↳ {event.summary}", style="dim")

        meta = []
        if event.sha:
            meta.append(f"commit: {event.sha}")
        if event.branch:
            meta.append(f"branch: {event.branch}")
        if event.duration_seconds is not None:
            meta.append(f"took: {event.duration_seconds}s")
        if "linked_dokploy_app" in event.details:
            meta.append(f"dokploy: {event.details['linked_dokploy_app']}")

        meta_text = Text(f" ({', '.join(meta)})", style="dim cyan") if meta else Text("")

        line = Text.assemble(
            Text(f"[{ts}] ", style="dim"),
            badge,
            Text(" "),
            target_text,
            title_text,
            meta_text,
            summary_text,
        )
        self.console.print(line)

    def render_status_table(
        self,
        runs: dict[str, list[WorkflowRun]],
        apps: list[ComposeApp],
        commits: Optional[dict[str, list[CommitEvent]]] = None,
        since_hours: float = 2.0,
    ) -> None:
        """Render a snapshot table of recent Git pushes, GitHub Actions, and Dokploy stacks."""
        self.console.print("\n[bold cyan]═══ TRACKPLOY DEPLOYMENT STATUS MATRIX ═══[/bold cyan]\n")

        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=since_hours)

        # 1. Recent Git Pushes Table
        push_table = Table(
            title=f"[bold cyan]Recent Git Pushes (Last {since_hours:g}h)[/bold cyan]",
            header_style="bold cyan",
            show_edge=True,
            show_header=True,
            expand=True,
        )
        push_table.add_column("Repository", style="bold cyan", min_width=20, max_width=26, overflow="ellipsis")
        push_table.add_column("Branch", style="green", min_width=10, max_width=16, overflow="ellipsis")
        push_table.add_column("Commit", style="yellow", width=8, no_wrap=True)
        push_table.add_column("Author", style="bright_white", min_width=10, max_width=16, overflow="ellipsis")
        push_table.add_column("Message", style="dim", min_width=22, max_width=42, overflow="ellipsis")
        push_table.add_column("Time", justify="right", style="dim", width=9, no_wrap=True)

        total_pushes = 0
        if commits:
            for repo, c_list in commits.items():
                for c in c_list:
                    c_ts = c.timestamp
                    if c_ts is not None:
                        c_ts_cmp = c_ts if c_ts.tzinfo is not None else c_ts.replace(tzinfo=timezone.utc)
                        if c_ts_cmp < cutoff:
                            continue
                    total_pushes += 1
                    ts_str = c.timestamp.strftime("%H:%M:%S") if c.timestamp else "-"
                    push_table.add_row(
                        repo,
                        c.branch,
                        c.sha[:7] if c.sha else "-",
                        c.author or "unknown",
                        c.message or "-",
                        ts_str,
                    )

        if total_pushes == 0:
            push_table.add_row("No recent pushes in window", "-", "-", "-", "-", "-")

        self.console.print(push_table)
        self.console.print("")

        # 2. GitHub Actions Table
        gh_table = Table(
            title=f"[bold magenta]GitHub Actions CI/CD (Last {since_hours:g}h)[/bold magenta]",
            header_style="bold magenta",
            show_edge=True,
            show_header=True,
            expand=True,
        )
        gh_table.add_column("Repository", style="bold cyan", min_width=20, max_width=26, overflow="ellipsis")
        gh_table.add_column("Workflow", style="bright_white", min_width=16, max_width=26, overflow="ellipsis")
        gh_table.add_column("Branch", style="green", min_width=8, max_width=14, overflow="ellipsis")
        gh_table.add_column("Commit", style="yellow", width=8, no_wrap=True)
        gh_table.add_column("Status", min_width=11, width=12, no_wrap=True)
        gh_table.add_column("Result", min_width=9, width=10, no_wrap=True)
        gh_table.add_column("Duration", justify="right", style="dim", width=9, no_wrap=True)
        gh_table.add_column("Time", justify="right", style="dim", width=9, no_wrap=True)

        total_runs = 0
        if runs:
            for repo, r_list in runs.items():
                for r in r_list:
                    r_ts = r.updated_at or r.started_at or r.created_at
                    if r_ts is not None:
                        r_ts_cmp = r_ts if r_ts.tzinfo is not None else r_ts.replace(tzinfo=timezone.utc)
                        if r_ts_cmp < cutoff:
                            continue
                    total_runs += 1
                    status_color = "yellow" if r.is_active else "green" if r.is_successful else "red" if r.is_failed else "white"
                    conc_str = r.conclusion.value.upper() if r.conclusion else "-"
                    conc_color = "green" if r.is_successful else "red" if r.is_failed else "dim"
                    dur_str = f"{r.duration_seconds}s" if r.duration_seconds else "-"
                    ts_str = r_ts.strftime("%H:%M:%S") if r_ts else "-"

                    gh_table.add_row(
                        repo,
                        r.workflow_name,
                        r.head_branch,
                        r.head_sha[:7] if r.head_sha else "-",
                        f"[{status_color}]{r.status.value.upper()}[/{status_color}]",
                        f"[{conc_color}]{conc_str}[/{conc_color}]",
                        dur_str,
                        ts_str,
                    )

        if total_runs == 0:
            gh_table.add_row("No tracked runs in window", "-", "-", "-", "-", "-", "-", "-")

        self.console.print(gh_table)
        self.console.print("")

        # 2. Dokploy Stacks Table
        dok_table = Table(
            title="[bold blue]Dokploy Swarm Stacks[/bold blue]",
            header_style="bold blue",
            show_edge=True,
            show_header=True,
            expand=True,
        )
        dok_table.add_column("Project", style="bold blue", min_width=14, max_width=18, overflow="ellipsis")
        dok_table.add_column("Stack Name", style="bright_white", min_width=14, max_width=22, overflow="ellipsis")
        dok_table.add_column("Compose ID", style="dim", width=14, no_wrap=True)
        dok_table.add_column("Status", min_width=8, width=9, no_wrap=True)
        dok_table.add_column("Latest Deployment", style="dim", min_width=18, max_width=28, overflow="ellipsis")
        dok_table.add_column("Deploy Time", justify="right", style="dim", width=19, no_wrap=True)

        if not apps:
            dok_table.add_row("No Dokploy stacks found", "-", "-", "-", "-", "-")
        else:
            for app in apps:
                st_color = (
                    "green" if app.compose_status == DokployStatus.DONE
                    else "yellow" if app.compose_status == DokployStatus.RUNNING
                    else "red" if app.compose_status == DokployStatus.ERROR
                    else "dim"
                )
                deploy_title = "-"
                deploy_ts = "-"
                if app.latest_deployment:
                    deploy_title = app.latest_deployment.title or app.latest_deployment.status.value
                    if app.latest_deployment.finished_at:
                        deploy_ts = app.latest_deployment.finished_at.strftime("%Y-%m-%d %H:%M:%S")
                    elif app.latest_deployment.started_at:
                        deploy_ts = app.latest_deployment.started_at.strftime("%Y-%m-%d %H:%M:%S")

                dok_table.add_row(
                    app.project_name,
                    app.name,
                    app.compose_id,
                    f"[{st_color}]{app.compose_status.value.upper()}[/{st_color}]",
                    deploy_title[:30],
                    deploy_ts,
                )

        self.console.print(dok_table)
        self.console.print("")
