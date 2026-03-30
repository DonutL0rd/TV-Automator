# 📺 TV-Automator

Self-hosted sports streaming appliance. Runs in Docker on an Ubuntu server connected to a TV via HDMI. Control it remotely through a terminal UI over SSH/Tailscale.

## What It Does

1. **You start the Docker container** on your Ubuntu server
2. **You SSH in** from another computer (via Tailscale)
3. **You see today's game schedule** in a terminal UI
4. **You select a game** → it starts playing on the TV

The system uses Google Chrome in kiosk mode for playback (handles DRM natively) and the MLB Stats API for schedule data.

## Quick Start

### Prerequisites

- Ubuntu server with HDMI connected to a monitor/TV
- Docker & Docker Compose installed
- X11 display server running (standard Ubuntu desktop, or minimal Openbox)
- Tailscale installed (for remote access)

### 1. Clone & Build

```bash
git clone <repo-url> TV-Automator
cd TV-Automator

# Allow Docker to access the display
xhost +local:docker

# Build and start
cd docker
docker compose up -d
```

### 2. Connect via SSH

```bash
# From your other computer (via Tailscale)
ssh root@<ubuntu-server-tailscale-ip>
# Default password: tvautomator
```

### 3. Launch the TUI

```bash
tv-automator
```

### 4. Login to MLB.TV

Press `L` in the TUI. A browser window will open on the TV — log in with your MLB.TV credentials there. Your session is saved so you only need to do this once.

### 5. Watch a Game

Use arrow keys to browse the schedule, press `Enter` to select a game. It starts playing on the TV.

## TUI Controls

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate games |
| `←` `→` | Previous/next day |
| `t` | Jump to today |
| `Enter` | Play selected game |
| `l` | Login to MLB.TV |
| `s` | Stop playback |
| `r` | Refresh schedule |
| `q` | Quit |

## Architecture

```
┌─────────────────────────────────────────────┐
│  Docker Container                           │
│                                             │
│  ┌──────────┐    ┌───────────────────────┐  │
│  │ TUI      │───▶│ Game Scheduler        │  │
│  │ (Textual)│    │ (MLB Stats API)       │  │
│  │          │    └───────────────────────┘  │
│  │          │                               │
│  │          │    ┌───────────────────────┐  │
│  │          │───▶│ Browser Controller    │  │
│  └──────────┘    │ (Playwright + Chrome) │  │
│       ↑          └──────────┬────────────┘  │
│       │                     │               │
│  SSH/Tailscale         X11 Socket           │
│                             │               │
└─────────────────────────────┼───────────────┘
                              │
                         HDMI Output
                              │
                         ┌────▼────┐
                         │   TV    │
                         └─────────┘
```

## Configuration

Edit `config/default.yaml` or create `/data/config/user.yaml`:

```yaml
providers:
  mlb:
    favorite_teams: ["NYY", "LAD"]  # Your teams
    auto_start: false                # Auto-play when favorites go live

scheduler:
  poll_interval: 60  # Seconds between schedule refreshes
```

## Project Structure

```
TV-Automator/
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── entrypoint.sh
│   └── openbox-config/rc.xml
├── src/tv_automator/
│   ├── main.py                    # Entry point
│   ├── config.py                  # Configuration
│   ├── providers/
│   │   ├── base.py                # Provider interface
│   │   └── mlb.py                 # MLB.TV adapter
│   ├── automator/
│   │   └── browser_control.py     # Playwright + Chrome
│   ├── scheduler/
│   │   └── game_scheduler.py      # Schedule polling
│   └── tui/
│       ├── app.py                 # Textual TUI
│       └── widgets/game_card.py   # Game display widget
├── config/default.yaml
└── pyproject.toml
```

## Roadmap

- [x] Phase 1: Single game playback with TUI control
- [ ] Phase 2: Auto-start games, session persistence, live scores
- [ ] Phase 3: Multiview (multiple simultaneous streams)
- [ ] Phase 4: F1 TV provider, then NBA/NHL/NFL

## Development

```bash
# Local dev (without Docker — needs Chrome installed)
pip install -e ".[dev]"
playwright install chromium
python -m tv_automator.main

# Run tests
pytest
```

## License

MIT
