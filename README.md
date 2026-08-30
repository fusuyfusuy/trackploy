# trackploy 🚀

> Continuous shell monitor and notifier for GitHub Actions CI/CD, Git pushes, and Dokploy Swarm deployments.

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stream](https://img.shields.io/badge/event_stream-SSE%200ms-purple.svg)](https://smee.io/)

`trackploy` bridges the gap between your local terminal, GitHub Actions workflows, real-time Smee webhooks, and self-hosted Dokploy Docker Swarm infrastructure into one continuous, unified pipeline tracker:

$$\text{Git Push} \longrightarrow \text{GitHub Actions CI} \longrightarrow \text{Dokploy Redeploy Nudge} \longrightarrow \text{Swarm Deployment}$$

---

## ✨ Features

- **Continuous Real-Time Terminal Feed**: Live event stream displaying active runs, build durations, deploy triggers, completions, and failure diagnostics.
- **Zero-Latency Smee.io Webhook Gateway**: Built-in Server-Sent Events (SSE) listener for instant 0ms push and workflow alerts.
- **Account & Org Global Event Streams**: Dynamically ingests activity across your entire GitHub account and organizations with zero static repository lists.
- **Unified Pipeline Correlation**: Automatically pairs repositories with corresponding Dokploy compose stacks using dynamic token and string normalization.
- **Dual GitHub Ingestion**:
  - **Primary**: Ultra-fast official `gh` CLI subprocess with environment token sanitation and host credential support.
  - **Secondary**: Automatic fallback to GitHub REST API (`httpx`) when CLI is unavailable.
- **Zero-Config Dokploy Discovery**: Reads `DOKPLOY_KEY` and `DOKPLOY_URL` from `.env` or environment variables without manual setup.
- **Native OSC 9 & OSC 777 Desktop Notifications**: Emits standard terminal escape sequences to trigger native OS desktop notification popups in modern terminals (Ghostty, Kitty, WezTerm, iTerm2, Alacritty, GNOME Terminal) with zero external daemons.
- **Desktop & Audio Alerts**: Optional D-Bus / `notify-send` desktop popups and audio terminal bells on CI/CD completions and failures.
- **Adaptive Cadence**: Dynamically polls faster (10s) during in-flight operations and backs off (25s) when the cluster and workflows are idle.

---

## 📦 Installation & Quickstart

```bash
# Clone and install in development mode using uv
git clone https://github.com/fusuyfusuy/trackploy.git
cd trackploy
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
- `-s, --smee <url>`: Smee.io Webhook channel URL for instant SSE streaming.
- `-r, --repo <owner/repo>`: Track specific repositories (repeatable).
- `-a, --active-interval <sec>`: Polling interval during active operations (default: 10s).
- `-i, --idle-interval <sec>`: Polling interval during idle periods (default: 25s).
- `--since-hours <hours>`: Startup lookback window for recent pushes and actions (default: 2.0h).
- `--no-osc`: Disable OSC terminal desktop notifications.
- `--no-bell`: Disable terminal bell chime on completion/failure.

### 2. Smee.io Real-Time Webhook Setup
Generate a free Smee.io SSE channel and optionally auto-attach it to GitHub repositories:
```bash
# Generate a channel and save to config
trackploy webhook setup

# Attach to specific repositories
trackploy webhook setup -r myorg/api -r myorg/web
```

### 3. One-Shot Status Matrix
Output a snapshot of all recent GitHub pushes, Actions, and Dokploy Swarm stacks:
```bash
trackploy status
```

### 4. Inspect Logs
View latest deployment records or failure logs:
```bash
# View Dokploy deployment history for a stack
trackploy logs api-service

# View latest CI run status / failure log for a repo
trackploy logs myorg/api
```

### 5. Trigger Redeployment
Manually nudge a Dokploy compose stack to redeploy:
```bash
trackploy trigger api-service
```

---

## ⚙️ Configuration Hierarchy

`trackploy` loads configuration in the following order:
1. **CLI Flags** (`--key`, `--url`, `--smee`, `--repo`, `--active-interval`)
2. **Environment Variables** (`DOKPLOY_KEY`, `DOKPLOY_URL`, `SMEE_URL`, `GITHUB_TOKEN`)
3. **Target `.env` File** (`.env` or `~/deployment/selfhosted/.env`)
4. **User Config File** (`~/.config/trackploy/config.json`)
5. **Auto-Discovery** (scans local project workspaces and dynamic GitHub feeds)

### Sample Configuration File (`~/.config/trackploy/config.json`)
```json
{
  "dokploy_url": "https://dokploy.yourdomain.com",
  "smee_url": "https://smee.io/your-channel-id",
  "active_interval_seconds": 10.0,
  "idle_interval_seconds": 25.0,
  "enable_osc_notifications": true,
  "enable_bell": true
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
│       │   ├── base.py          # Pluggable CiSource & DeploySource protocols
│       │   ├── smee.py          # Smee.io Server-Sent Events (SSE) client
│       │   ├── github_cli.py    # Primary: gh CLI adapter & global streams
│       │   ├── github_api.py    # Secondary: GitHub REST fallback
│       │   └── dokploy.py       # Dokploy REST API client
│       ├── core/
│       │   ├── poller.py        # Adaptive async polling & stream engine
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
