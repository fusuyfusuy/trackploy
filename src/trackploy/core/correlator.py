"""Correlates GitHub repository activity with Dokploy compose stacks."""

from typing import Optional
from trackploy.models import ComposeApp, TrackployEvent, WorkflowRun


class PipelineCorrelator:
    """Correlates GitHub actions, pushes, and Dokploy deployments."""

    def __init__(self, repo_stack_map: dict[str, str]):
        self.repo_stack_map = repo_stack_map
        # Inverted mapping: stack -> list of repos
        self.stack_repo_map: dict[str, list[str]] = {}
        for r, s in repo_stack_map.items():
            self.stack_repo_map.setdefault(s.lower(), []).append(r)

    def get_stack_for_repo(self, repo: str) -> Optional[str]:
        """Find the Dokploy compose stack name for a GitHub repo."""
        if repo in self.repo_stack_map:
            return self.repo_stack_map[repo]
        # Try base repo name
        base_name = repo.split("/")[-1]
        if base_name in self.repo_stack_map:
            return self.repo_stack_map[base_name]
        return None

    def match_app_for_repo(self, repo: str, apps: list[ComposeApp]) -> Optional[ComposeApp]:
        """Find the matching ComposeApp from a list of Dokploy apps for a repo."""
        target_stack = self.get_stack_for_repo(repo)
        repo_base = repo.split("/")[-1].lower()

        for app in apps:
            app_name = app.name.lower()
            if target_stack and app_name == target_stack.lower():
                return app
            if app_name == repo_base:
                return app
            if app.app_name and target_stack and target_stack.lower() in app.app_name.lower():
                return app

        return None

    def enrich_event(self, event: TrackployEvent, apps: list[ComposeApp]) -> TrackployEvent:
        """Enrich an event with linked repository or stack metadata."""
        if event.source == "github":
            matched_app = self.match_app_for_repo(event.target, apps)
            if matched_app:
                event.details["linked_dokploy_app"] = matched_app.name
                event.details["dokploy_compose_id"] = matched_app.compose_id
                event.details["dokploy_status"] = matched_app.compose_status.value
        return event
