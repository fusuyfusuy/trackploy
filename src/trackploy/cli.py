"""Command-line interface for trackploy."""

import asyncio
import sys
from typing import Optional
import click
from rich.console import Console
from rich.panel import Panel
from trackploy.config import TrackployConfig
from trackploy.core.poller import PollingEngine
from trackploy.notifiers.console import ConsoleNotifier
from trackploy.notifiers.desktop import DesktopNotifier
from trackploy.notifiers.osc import OscNotifier


console = Console()


@click.group(invoke_without_command=True)
@click.option("--key", "-k", help="Dokploy API Key")
@click.option("--url", "-u", help="Dokploy Base URL")
@click.option("--repo", "-r", "repos", multiple=True, help="Specific GitHub repos to track (e.g. fusuycorp/boun-scrape)")
@click.option("--active-interval", "-a", type=float, default=None, help="Polling interval during active runs/deployments (seconds)")
@click.option("--idle-interval", "-i", type=float, default=None, help="Polling interval during idle periods (seconds)")
@click.option("--since-hours", type=float, default=None, help="Lookback window in hours for startup pushes and actions (default: 2.0)")
@click.option("--no-osc", is_flag=True, default=False, help="Disable OSC 9/777 terminal desktop notifications")
@click.option("--no-bell", is_flag=True, default=False, help="Disable terminal bell alerts")
@click.pass_context
def main(
    ctx: click.Context,
    key: Optional[str],
    url: Optional[str],
    repos: tuple[str, ...],
    active_interval: Optional[float],
    idle_interval: Optional[float],
    since_hours: Optional[float],
    no_osc: bool,
    no_bell: bool,
):
    """trackploy: Continuous GitHub Actions, Git Pushes, and Dokploy Deployment Tracker."""
    config = TrackployConfig.load(
        dokploy_key=key,
        dokploy_url=url,
        repos=list(repos) if repos else None,
        history_window_hours=since_hours,
    )
    if active_interval is not None:
        config.active_interval_seconds = active_interval
    if idle_interval is not None:
        config.idle_interval_seconds = idle_interval
    if no_osc:
        config.enable_osc_notifications = False
    if no_bell:
        config.enable_bell = False

    ctx.obj = config

    if ctx.invoked_subcommand is None:
        ctx.invoke(watch)


@main.command()
@click.pass_obj
def status(config: TrackployConfig):
    """Show current snapshot of GitHub Actions and Dokploy stacks."""
    engine = PollingEngine(config)
    console_notifier = ConsoleNotifier(console)

    with console.status("[bold cyan]Fetching latest status from GitHub and Dokploy...[/bold cyan]"):
        asyncio.run(engine.poll_once())

    console_notifier.render_status_table(
        runs=engine.latest_runs,
        apps=engine.latest_apps,
        commits=engine.latest_commits,
        since_hours=config.history_window_hours,
    )


@main.command()
@click.pass_obj
def watch(config: TrackployConfig):
    """Continuously monitor GitHub Actions, pushes, and Dokploy deployments in real-time."""
    engine = PollingEngine(config)
    console_notifier = ConsoleNotifier(console)
    osc_notifier = OscNotifier(
        enable_bell=config.enable_bell,
        enable_osc=config.enable_osc_notifications,
    )
    desktop_notifier = DesktopNotifier(
        enable_desktop=config.enable_desktop_notifications,
    )

    console.print(Panel.fit(
        f"[bold bright_white]Trackploy Continuous Monitor[/bold bright_white]\n"
        f"[dim]Dokploy URL:[/dim] [cyan]{config.dokploy_url}[/cyan]\n"
        f"[dim]Tracked Repos ({len(config.tracked_repos)}):[/dim] {', '.join(config.tracked_repos[:4])}{'...' if len(config.tracked_repos) > 4 else ''}\n"
        f"[dim]Intervals:[/dim] Active: {config.active_interval_seconds}s | Idle: {config.idle_interval_seconds}s\n"
        f"[dim]OSC Notifications:[/dim] {'Enabled' if config.enable_osc_notifications else 'Disabled'} | [dim]Bell:[/dim] {'Enabled' if config.enable_bell else 'Disabled'}\n"
        f"[dim italic]Press Ctrl+C to exit.[/dim italic]",
        border_style="cyan",
    ))

    async def _runner():
        # First poll to initialize and render baseline snapshot
        with console.status("[bold cyan]Initializing trackploy baseline...[/bold cyan]"):
            await engine.poll_once()

        console_notifier.render_status_table(
            runs=engine.latest_runs,
            apps=engine.latest_apps,
            commits=engine.latest_commits,
            since_hours=config.history_window_hours,
        )

        console.print("[bold green]● Live stream listening for GitHub pushes, CI workflows, and Dokploy redeploys...[/bold green]\n")

        try:
            async for event_batch in engine.run_loop():
                for evt in event_batch:
                    console_notifier.render_event(evt)
                    osc_notifier.notify(evt)
                    await desktop_notifier.notify(evt)
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        console.print("\n[yellow]Trackploy monitor stopped.[/yellow]")
        sys.exit(0)


@main.command()
@click.argument("service_name")
@click.pass_obj
def trigger(config: TrackployConfig, service_name: str):
    """Trigger a redeployment of a Dokploy compose stack by name or ID."""
    engine = PollingEngine(config)

    async def _trigger():
        with console.status(f"[bold cyan]Locating Dokploy service '{service_name}'...[/bold cyan]"):
            apps = await engine.dokploy.get_all_apps(fetch_details=False)

        target_app = None
        for app in apps:
            if app.compose_id == service_name or app.name.lower() == service_name.lower():
                target_app = app
                break

        if not target_app:
            console.print(f"[bold red]Error:[/] Could not find Dokploy compose stack matching '{service_name}'.")
            console.print(f"Available stacks: {', '.join(a.name for a in apps)}")
            return

        with console.status(f"[bold blue]Triggering redeployment for {target_app.name} ({target_app.compose_id})...[/bold blue]"):
            success, msg = await engine.dokploy.trigger_redeploy(target_app.compose_id)

        if success:
            console.print(f"[bold green]✓ Redeployment successfully triggered for {target_app.name}![/bold green]")
        else:
            console.print(f"[bold red]✗ Redeploy failed:[/] {msg}")

    asyncio.run(_trigger())


@main.command()
@click.argument("target")
@click.pass_obj
def logs(config: TrackployConfig, target: str):
    """View recent logs for a GitHub repo (failed CI) or Dokploy stack (latest deploy)."""
    engine = PollingEngine(config)

    async def _logs():
        # Check if target is a GitHub repo
        if "/" in target or target in config.tracked_repos:
            runs = await engine._fetch_repo_runs(target)
            if not runs:
                console.print(f"[yellow]No runs found for repo {target}[/yellow]")
                return
            latest_run = runs[0]
            console.print(f"[bold cyan]Latest run for {target}:[/bold cyan] {latest_run.workflow_name} (#{latest_run.id}) - Status: {latest_run.status.value}, Conclusion: {latest_run.conclusion.value if latest_run.conclusion else 'none'}")
            if latest_run.is_failed:
                log_content = await engine.gh_cli.get_failed_logs(target, latest_run.id)
                if log_content:
                    console.print(Panel(log_content[:2000], title="Failure Logs", border_style="red"))
                else:
                    console.print("[dim]No failure log snippet could be extracted via gh CLI.[/dim]")
            return

        # Otherwise check Dokploy apps
        apps = await engine.dokploy.get_all_apps(fetch_details=True)
        matched_app = None
        for a in apps:
            if a.compose_id == target or a.name.lower() == target.lower():
                matched_app = a
                break

        if matched_app:
            console.print(f"[bold cyan]Dokploy Stack:[/] {matched_app.name} ({matched_app.project_name})")
            console.print(f"Status: {matched_app.compose_status.value}")
            if matched_app.recent_deployments:
                console.print("\n[bold]Recent Deployments:[/bold]")
                for d in matched_app.recent_deployments:
                    console.print(f"- [{d.deployment_id}] {d.status.value.upper()}: {d.title or ''} ({d.finished_at or d.started_at or '-'})")
                    if d.error_message:
                        console.print(f"  [red]Error: {d.error_message}[/red]")
            return

        console.print(f"[bold red]Target '{target}' not found as a GitHub repo or Dokploy compose stack.[/bold red]")

    asyncio.run(_logs())


if __name__ == "__main__":
    main()
