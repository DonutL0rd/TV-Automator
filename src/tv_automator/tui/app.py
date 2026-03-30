"""TV-Automator TUI application built with Textual."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Label, Static, Button, LoadingIndicator

from tv_automator.automator.browser_control import BrowserController
from tv_automator.config import Config
from tv_automator.providers.base import Game, GameStatus, StreamingProvider
from tv_automator.providers.mlb import MLBProvider
from tv_automator.scheduler.game_scheduler import GameScheduler
from tv_automator.tui.widgets.game_card import GameCard

log = logging.getLogger(__name__)


# ── Confirm Dialog ──────────────────────────────────────────────

class ConfirmDialog(ModalScreen[bool]):
    """Simple yes/no confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }

    ConfirmDialog > Container {
        width: 60;
        height: auto;
        max-height: 12;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }

    ConfirmDialog .message {
        margin-bottom: 1;
    }

    ConfirmDialog Horizontal {
        align: center middle;
        height: 3;
    }

    ConfirmDialog Button {
        margin: 0 1;
        min-width: 10;
    }
    """

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(self._message, classes="message")
            with Horizontal():
                yield Button("Yes", variant="success", id="yes")
                yield Button("No", variant="error", id="no")

    @on(Button.Pressed, "#yes")
    def on_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def on_no(self) -> None:
        self.dismiss(False)

    def on_key(self, event) -> None:
        if event.key == "y":
            self.dismiss(True)
        elif event.key == "n" or event.key == "escape":
            self.dismiss(False)


# ── Login Screen ────────────────────────────────────────────────

class LoginScreen(ModalScreen[bool]):
    """Screen shown during the manual login flow."""

    DEFAULT_CSS = """
    LoginScreen {
        align: center middle;
    }

    LoginScreen > Container {
        width: 70;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 2 3;
    }

    LoginScreen .title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    LoginScreen .instructions {
        margin-bottom: 1;
        color: $text-muted;
    }

    LoginScreen .status {
        text-align: center;
        margin: 1 0;
    }
    """

    def __init__(self, provider_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._provider_name = provider_name

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(f"🔐 Login to {self._provider_name}", classes="title")
            yield Label(
                "A browser window has opened on your TV display.\n"
                "Please log in using the browser on the connected monitor.\n"
                "This screen will close automatically when login is detected.\n\n"
                "If you can't see the monitor, you can use VNC to view it.",
                classes="instructions",
            )
            yield Label("⏳ Waiting for login...", id="login-status", classes="status")
            yield Button("Cancel", variant="error", id="cancel-login")

    @on(Button.Pressed, "#cancel-login")
    def on_cancel(self) -> None:
        self.dismiss(False)


# ── Main Application ────────────────────────────────────────────

class TVAutomatorApp(App):
    """TV-Automator Terminal User Interface."""

    TITLE = "📺 TV-Automator"
    SUB_TITLE = "Self-Hosted Sports Streaming"

    CSS = """
    Screen {
        background: $background;
    }

    #main-container {
        height: 1fr;
    }

    /* ── Header bar ─────────────────────────────────────────── */

    #top-bar {
        height: 3;
        background: $primary-background;
        padding: 0 2;
        layout: horizontal;
    }

    #top-bar .date-nav {
        width: auto;
        min-width: 30;
        content-align: center middle;
        text-style: bold;
    }

    #top-bar .now-playing {
        width: 1fr;
        content-align: right middle;
        color: $success;
    }

    /* ── Schedule panel ─────────────────────────────────────── */

    #schedule-panel {
        height: 1fr;
    }

    #schedule-header {
        height: 3;
        background: $surface;
        padding: 0 2;
        layout: horizontal;
    }

    #schedule-header Label {
        content-align: center middle;
    }

    #schedule-header .col-time {
        width: 10;
        color: $text-muted;
        text-style: bold;
    }
    #schedule-header .col-matchup {
        width: 1fr;
        color: $text-muted;
        text-style: bold;
    }
    #schedule-header .col-score {
        width: 12;
        color: $text-muted;
        text-style: bold;
    }
    #schedule-header .col-status {
        width: 14;
        color: $text-muted;
        text-style: bold;
    }

    #game-list {
        height: 1fr;
    }

    #no-games {
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
        text-style: italic;
    }

    #loading {
        height: 1fr;
        content-align: center middle;
    }

    /* ── Status bar ─────────────────────────────────────────── */

    #status-bar {
        height: 3;
        background: $surface;
        padding: 0 2;
        layout: horizontal;
        dock: bottom;
    }

    #status-bar .auth-status {
        width: auto;
        min-width: 20;
        content-align: left middle;
    }

    #status-bar .provider-status {
        width: 1fr;
        content-align: center middle;
        color: $text-muted;
    }

    #status-bar .clock {
        width: 20;
        content-align: right middle;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "login", "Login"),
        Binding("s", "stop_playback", "Stop"),
        Binding("left", "prev_day", "Prev Day"),
        Binding("right", "next_day", "Next Day"),
        Binding("t", "today", "Today"),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self._config = config or Config()
        self._scheduler = GameScheduler(self._config)
        self._browser = BrowserController(self._config)
        self._current_date = datetime.now()
        self._is_authenticated = False
        self._now_playing: Game | None = None
        self._favorite_teams = {t.upper() for t in self._config.favorite_teams}

        # Register providers
        self._mlb = MLBProvider()
        self._scheduler.register_provider(self._mlb)

    # ── Compose ─────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="main-container"):
            # Top bar with date navigation and now-playing
            with Horizontal(id="top-bar"):
                yield Label(self._format_date(), classes="date-nav", id="date-label")
                yield Label("", classes="now-playing", id="now-playing-label")

            # Schedule panel
            with Vertical(id="schedule-panel"):
                # Column headers
                with Horizontal(id="schedule-header"):
                    yield Label("Time", classes="col-time")
                    yield Label("Matchup", classes="col-matchup")
                    yield Label("Score", classes="col-score")
                    yield Label("Status", classes="col-status")

                # Game list (scrollable)
                yield VerticalScroll(id="game-list")

                # Loading / no-games states
                yield Label("Loading schedule...", id="loading")
                yield Label("No games scheduled for this date", id="no-games")

            # Status bar
            with Horizontal(id="status-bar"):
                yield Label("🔴 Not logged in", classes="auth-status", id="auth-label")
                yield Label("MLB.TV | Press [bold]L[/] to login", classes="provider-status")
                yield Label("", classes="clock", id="clock-label")

        yield Footer()

    # ── Lifecycle ───────────────────────────────────────────────

    async def on_mount(self) -> None:
        """Start services when the app mounts."""
        # Hide initial states
        self.query_one("#no-games").display = False
        self.query_one("#loading").display = True
        self.query_one("#game-list").display = False

        # Start the browser and scheduler in the background
        self.start_services()

        # Start the clock
        self.set_interval(1, self._update_clock)

        # Periodic schedule refresh in the TUI
        self.set_interval(60, self._refresh_display)

    @work(exclusive=True)
    async def start_services(self) -> None:
        """Start browser and scheduler services."""
        try:
            await self._browser.start()
            self.log.info("Browser started")
        except Exception as e:
            self.log.error(f"Browser start failed: {e}")
            self.notify(
                f"Browser failed to start: {e}\nPlayback won't work until browser is running.",
                severity="error",
                timeout=10,
            )

        # Check auth status
        try:
            self._is_authenticated = await self._browser.is_authenticated(self._mlb)
            self._update_auth_label()
        except Exception:
            pass

        # Load initial schedule
        await self._load_schedule()

    async def action_quit(self) -> None:
        """Graceful shutdown."""
        await self._scheduler.stop()
        await self._browser.stop()
        self.exit()

    # ── Schedule management ─────────────────────────────────────

    async def _load_schedule(self) -> None:
        """Load schedule for the current date."""
        self.query_one("#loading").display = True
        self.query_one("#game-list").display = False
        self.query_one("#no-games").display = False

        try:
            games = await self._mlb.get_schedule(self._current_date)
            self._render_games(games)
        except Exception as e:
            self.log.error(f"Failed to load schedule: {e}")
            self.notify(f"Failed to load schedule: {e}", severity="error")
            self.query_one("#loading").display = False
            self.query_one("#no-games").display = True

    def _render_games(self, games: list[Game]) -> None:
        """Render game cards into the game list."""
        game_list = self.query_one("#game-list", VerticalScroll)
        game_list.remove_children()

        self.query_one("#loading").display = False

        if not games:
            self.query_one("#no-games").display = True
            self.query_one("#game-list").display = False
            return

        self.query_one("#no-games").display = False
        self.query_one("#game-list").display = True

        for game in games:
            card = GameCard(game, favorite_teams=self._favorite_teams)
            game_list.mount(card)

        # Focus the first card
        first_card = game_list.query("GameCard").first()
        if first_card:
            first_card.focus()

    # ── Actions ─────────────────────────────────────────────────

    @work(exclusive=True)
    async def action_refresh(self) -> None:
        """Refresh the schedule."""
        self.notify("Refreshing schedule...")
        await self._load_schedule()

    @work(exclusive=True)
    async def action_login(self) -> None:
        """Start the login flow."""
        if self._is_authenticated:
            self.notify("Already logged in to MLB.TV", severity="information")
            return

        # Show login instructions
        result = await self.push_screen_wait(
            LoginScreen(self._mlb.display_name),
        )

        if result is False:
            self.notify("Login cancelled")
            return

    @work(exclusive=True)
    async def action_login_start(self) -> None:
        """Actually perform the login (called after showing instructions)."""
        try:
            success = await self._browser.login(self._mlb)
            self._is_authenticated = success
            self._update_auth_label()

            if success:
                self.notify("✅ Logged in to MLB.TV!", severity="information")
            else:
                self.notify("❌ Login failed or timed out", severity="error")
        except Exception as e:
            self.notify(f"Login error: {e}", severity="error")

    async def action_stop_playback(self) -> None:
        """Stop current playback."""
        await self._browser.stop_playback()
        self._now_playing = None
        self._update_now_playing_label()
        self.notify("Playback stopped")

    async def action_prev_day(self) -> None:
        """Navigate to previous day."""
        self._current_date -= timedelta(days=1)
        self._update_date_label()
        await self._load_schedule()

    async def action_next_day(self) -> None:
        """Navigate to next day."""
        self._current_date += timedelta(days=1)
        self._update_date_label()
        await self._load_schedule()

    async def action_today(self) -> None:
        """Navigate to today."""
        self._current_date = datetime.now()
        self._update_date_label()
        await self._load_schedule()

    # ── Event handlers ──────────────────────────────────────────

    @on(GameCard.Selected)
    async def on_game_selected(self, event: GameCard.Selected) -> None:
        """Handle game selection — start playback."""
        game = event.game

        if not self._is_authenticated:
            self.notify(
                "Please login first (press L)",
                severity="warning",
            )
            return

        if not game.status.is_watchable and game.status != GameStatus.FINAL:
            self.notify(
                f"Game is {game.status.display_label} — not yet available",
                severity="warning",
            )
            return

        # Confirm
        confirmed = await self.push_screen_wait(
            ConfirmDialog(f"Play {game.display_matchup}?"),
        )

        if not confirmed:
            return

        self.notify(f"Starting {game.display_matchup}...")
        self._play_game(game)

    @work(exclusive=True)
    async def _play_game(self, game: Game) -> None:
        """Play the selected game."""
        try:
            success = await self._browser.play_game(self._mlb, game)
            if success:
                self._now_playing = game
                self._update_now_playing_label()
                self.notify(f"▶ Now playing: {game.display_matchup}", severity="information")
            else:
                self.notify("Failed to start playback", severity="error")
        except Exception as e:
            self.notify(f"Playback error: {e}", severity="error")

    # ── UI helpers ──────────────────────────────────────────────

    def _format_date(self) -> str:
        today = datetime.now().date()
        d = self._current_date.date()
        if d == today:
            label = "Today"
        elif d == today - timedelta(days=1):
            label = "Yesterday"
        elif d == today + timedelta(days=1):
            label = "Tomorrow"
        else:
            label = d.strftime("%A")
        return f"◀ {label} — {d.strftime('%B %-d, %Y')} ▶"

    def _update_date_label(self) -> None:
        self.query_one("#date-label", Label).update(self._format_date())

    def _update_auth_label(self) -> None:
        label = self.query_one("#auth-label", Label)
        if self._is_authenticated:
            label.update("🟢 Logged in")
        else:
            label.update("🔴 Not logged in")

    def _update_now_playing_label(self) -> None:
        label = self.query_one("#now-playing-label", Label)
        if self._now_playing:
            label.update(f"▶ {self._now_playing.display_matchup}")
        else:
            label.update("")

    def _update_clock(self) -> None:
        self.query_one("#clock-label", Label).update(
            datetime.now().strftime("%-I:%M:%S %p")
        )

    async def _refresh_display(self) -> None:
        """Periodic refresh for live score updates."""
        if self._current_date.date() == datetime.now().date():
            games = await self._mlb.get_schedule(self._current_date)
            # Update existing cards instead of rebuilding
            game_list = self.query_one("#game-list", VerticalScroll)
            cards = game_list.query("GameCard")
            game_map = {g.game_id: g for g in games}

            for card in cards:
                if card._game.game_id in game_map:
                    card.update_game(game_map[card._game.game_id])
