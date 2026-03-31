"""Abstract base class for streaming providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class GameStatus(Enum):
    """Status of a game."""
    SCHEDULED = "scheduled"
    PRE_GAME = "pre_game"
    LIVE = "live"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @property
    def is_watchable(self) -> bool:
        return self in (GameStatus.LIVE, GameStatus.PRE_GAME)

    @property
    def display_label(self) -> str:
        labels = {
            GameStatus.SCHEDULED: "Scheduled",
            GameStatus.PRE_GAME: "Pre-Game",
            GameStatus.LIVE: "LIVE",
            GameStatus.FINAL: "Final",
            GameStatus.POSTPONED: "Postponed",
            GameStatus.CANCELLED: "Cancelled",
            GameStatus.UNKNOWN: "Unknown",
        }
        return labels.get(self, self.value)


@dataclass
class Team:
    """A sports team."""
    name: str
    abbreviation: str
    score: int | None = None


@dataclass
class Game:
    """A single game from any provider."""
    game_id: str
    provider: str  # e.g. "mlb", "f1"
    away_team: Team
    home_team: Team
    start_time: datetime
    status: GameStatus = GameStatus.SCHEDULED
    venue: str = ""
    description: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def display_time(self) -> str:
        return self.start_time.strftime("%-I:%M %p")

    @property
    def display_matchup(self) -> str:
        return f"{self.away_team.abbreviation} @ {self.home_team.abbreviation}"

    @property
    def display_score(self) -> str:
        if self.away_team.score is not None and self.home_team.score is not None:
            return f"{self.away_team.score} - {self.home_team.score}"
        return ""

    @property
    def summary(self) -> str:
        parts = [self.display_time, self.display_matchup]
        if score := self.display_score:
            parts.append(score)
        parts.append(self.status.display_label)
        return " | ".join(parts)


class StreamingProvider(ABC):
    """Abstract base class all streaming providers must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @abstractmethod
    async def get_schedule(self, date: datetime) -> list[Game]:
        ...

    @abstractmethod
    async def get_game_status(self, game_id: str) -> GameStatus:
        ...
