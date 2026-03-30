"""Game card widget for TUI schedule display."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static

from tv_automator.providers.base import Game, GameStatus


class GameCard(Widget):
    """
    A single game entry in the schedule list.
    Shows: time | away @ home | score | status
    Highlights live games and favorite teams.
    """

    DEFAULT_CSS = """
    GameCard {
        height: 3;
        margin: 0 1;
        padding: 0 1;
        background: $surface;
        border: tall $border-color;
        layout: horizontal;
    }

    GameCard:hover {
        background: $surface-lighten-1;
        border: tall $accent;
    }

    GameCard:focus {
        background: $surface-lighten-2;
        border: tall $accent;
    }

    GameCard.live {
        border: tall $success;
    }

    GameCard.live .status {
        color: $success;
    }

    GameCard.final .status {
        color: $text-muted;
    }

    GameCard.favorite {
        border: tall $warning;
    }

    GameCard .time {
        width: 10;
        content-align: center middle;
        color: $text-muted;
    }

    GameCard .matchup {
        width: 1fr;
        content-align: center middle;
    }

    GameCard .score {
        width: 12;
        content-align: center middle;
        text-style: bold;
    }

    GameCard .status {
        width: 14;
        content-align: center middle;
    }

    GameCard .venue {
        width: 20;
        content-align: center middle;
        color: $text-muted;
    }
    """

    can_focus = True

    game: reactive[Game | None] = reactive(None)

    class Selected(Message):
        """Emitted when a game card is selected (Enter key)."""
        def __init__(self, game: Game) -> None:
            super().__init__()
            self.game = game

    def __init__(self, game: Game, favorite_teams: set[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._game = game
        self._favorite_teams = favorite_teams or set()

    def compose(self) -> ComposeResult:
        g = self._game
        with Horizontal():
            yield Label(g.display_time, classes="time")
            yield Label(f"{g.away_team.name} @ {g.home_team.name}", classes="matchup")
            yield Label(g.display_score or "—", classes="score")
            yield Label(g.status.display_label, classes="status")

    def on_mount(self) -> None:
        g = self._game
        # Add CSS classes based on game state
        if g.status == GameStatus.LIVE:
            self.add_class("live")
        elif g.status == GameStatus.FINAL:
            self.add_class("final")

        # Highlight favorite teams
        teams = {g.away_team.abbreviation.upper(), g.home_team.abbreviation.upper()}
        if teams & self._favorite_teams:
            self.add_class("favorite")

    def on_key(self, event) -> None:
        if event.key == "enter":
            self.post_message(self.Selected(self._game))

    def on_click(self) -> None:
        self.post_message(self.Selected(self._game))

    def update_game(self, game: Game) -> None:
        """Update the game data and refresh display."""
        self._game = game
        # Update labels
        try:
            self.query_one(".score", Label).update(game.display_score or "—")
            self.query_one(".status", Label).update(game.status.display_label)
        except NoMatches:
            pass

        # Update classes
        self.remove_class("live", "final")
        if game.status == GameStatus.LIVE:
            self.add_class("live")
        elif game.status == GameStatus.FINAL:
            self.add_class("final")
