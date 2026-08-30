# trackploy 🚀

> Continuous shell monitor and notifier for GitHub Actions CI/CD, Git pushes, and Dokploy Swarm deployments.

`trackploy` bridges the gap between your local terminal, GitHub Actions workflows, and self-hosted Dokploy Docker Swarm infrastructure into one continuous, unified pipeline tracker:

$$\text{Git Push} \longrightarrow \text{GitHub Actions CI} \longrightarrow \text{Dokploy Redeploy Nudge} \longrightarrow \text{Swarm Deployment}$$

---

## ✨ Features

- **Continuous Real-Time Terminal Feed**: Live event stream displaying active runs, build durations, deploy triggers, completions, and failure diagnostics.
- **Unified Pipeline Correlation**: Automatically pairs GitHub repositories (e.g. `fusuycorp/boun-scrape`) with corresponding Dokploy compose stacks (e.g. `scraper`).
- **Dual GitHub Ingestion**:
  - **Primary**: Ultra-fast official `gh` CLI subprocess with environment token sanitation and host credential support.
  - **Secondary**: Automatic fallback to GitHub REST API (`httpx`) when CLI is unavailable.
- **Zero-Config Dokploy Discovery**: Reads `DOKPLOY_KEY` and `DOKPLOY_URL` directly from `~/deployment/selfhosted/.env` or environment variables without manual setup.
- **Native OSC 9 & OSC 777 Desktop Notifications**: Emits standard terminal escape sequences to trigger native OS desktop notification popups in modern terminals (Ghostty, Kitty, WezTerm, iTerm2, Alacritty, GNOME Terminal) with zero external daemons.
- **Desktop & Audio Alerts**: Optional D-Bus / `notify-send` desktop popups and audio terminal bells on CI/CD completions and failures.
- **Adaptive Polling Engine**: Dynamically polls faster (10s) during in-flight operations and backs off (25s) when the cluster and workflows are idle.

---

## 📦 Installation & Quickstart

```bash
# Clone and install in development mode using uv
cd ~/projects/fusuyfusuy/trackploy
uv sync
uv pip install -e .
```

---

## 🛠️ CLI Usage

### 1. Continuous Watch Mode (Default)
Run `trackploy` persistently in a dedicated shell or terminal tab:
```bash
trackploy watch
# or simply
trackploy
```

Options:
- `-r, --repo <owner/repo>`: Track specific repositories (repeatable).
- `-a, --active-interval <sec>`: Polling interval during active operations (default: 10s).
- `-i, --idle-interval <sec>`: Polling interval during idle periods (default: 25s).
- `--no-osc`: Disable OSC terminal desktop notifications.
- `--no-bell`: Disable terminal bell chime on completion/failure.

### 2. One-Shot Status Matrix
Output a snapshot of all tracked GitHub Actions and Dokploy Swarm stacks:
```bash
trackploy status
```

### 3. Inspect Logs
View latest deployment records or failure logs:
```bash
# View Dokploy deployment history for a stack
trackploy logs scraper

# View latest CI run status / failure log for a repo
trackploy logs fusuycorp/boun-scrape
```

### 4. Trigger Redeployment
Manually nudge a Dokploy compose stack to redeploy:
```bash
trackploy trigger scraper
```

---

## ⚙️ Configuration Hierarchy

`trackploy` loads configuration in the following order:
1. **CLI Flags** (`--key`, `--url`, `--repo`, `--active-interval`)
2. **Environment Variables** (`DOKPLOY_KEY`, `DOKPLOY_URL`, `GITHUB_TOKEN`)
3. **User Config File** (`~/.config/trackploy/config.json`)
4. **Selfhosted Environment File** (`~/deployment/selfhosted/.env`)
5. **Auto-Discovery** (scans local project workspaces for active workflows and Dokploy stacks)

### Sample Configuration File (`~/.config/trackploy/config.json`)
```json
{
  "dokploy_url": "https://dokploy.bogazici.app",
  "active_interval_seconds": 10.0,
  "idle_interval_seconds": 25.0,
  "enable_osc_notifications": true,
  "enable_bell": true,
  "tracked_repos": [
    "fusuycorp/boun-scrape",
    "fusuycorp/hepyeni",
    "fusuycorp/3d-filament-finder",
    "fusuycorp/yokatlas-scrape"
  ],
  "repo_stack_map": {
    "fusuycorp/boun-scrape": "scraper",
    "fusuycorp/hepyeni": "hepyeni",
    "fusuycorp/3d-filament-finder": "filament",
    "fusuycorp/yokatlas-scrape": "uni-tercih"
  }
}
```

---

## 🧪 Running Tests

```bash
uv run pytest
```

---

## 📂 Project Structure

```text
trackploy/
├── pyproject.toml
├── README.md
├── src/
│   └── trackploy/
│       ├── __init__.py
│       ├── __main__.py          # Entry point (python -m trackploy)
│       ├── cli.py               # Click CLI command suite
│       ├── config.py            # Hierarchical config & auto-discovery
│       ├── models.py            # Pydantic boundary models
│       ├── sources/
│       │   ├── github_cli.py    # Primary: gh CLI adapter
│       │   ├── github_api.py    # Secondary: GitHub REST fallback
│       │   └── dokploy.py       # Dokploy REST API client
│       ├── core/
│       │   ├── poller.py        # Adaptive async polling loop
│       │   ├── state.py         # State machine & transition deduplicator
│       │   └── correlator.py    # Cross-source pipeline correlation
│       └── notifiers/
│           ├── console.py       # Rich terminal tables & live badges
│           ├── osc.py           # OSC 9/777 terminal desktop notifications
│           └── desktop.py       # notify-send desktop notifications
└── tests/
    ├── test_models.py
    ├── test_config.py
    ├── test_sources.py
    ├── test_state_and_correlator.py
    └── test_poller.py
```
