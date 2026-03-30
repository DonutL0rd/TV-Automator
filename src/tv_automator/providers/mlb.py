"""MLB.TV streaming provider."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import statsapi

from .base import Game, GameStatus, StreamingProvider, Team

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

log = logging.getLogger(__name__)

# MLB Stats API status codes → our GameStatus enum
_STATUS_MAP: dict[str, GameStatus] = {
    "Pre-Game": GameStatus.PRE_GAME,
    "Warmup": GameStatus.PRE_GAME,
    "Scheduled": GameStatus.SCHEDULED,
    "In Progress": GameStatus.LIVE,
    "Live": GameStatus.LIVE,
    "Game Over": GameStatus.FINAL,
    "Final": GameStatus.FINAL,
    "Postponed": GameStatus.POSTPONED,
    "Cancelled": GameStatus.CANCELLED,
    "Suspended": GameStatus.POSTPONED,
    "Delayed": GameStatus.PRE_GAME,
    "Delayed Start": GameStatus.PRE_GAME,
}

# MLB.TV URLs
MLB_TV_URL = "https://www.mlb.tv"
MLB_LOGIN_URL = "https://www.mlb.com/login"
MLB_TV_GAME_URL = "https://www.mlb.tv/game/{game_id}"


class MLBProvider(StreamingProvider):
    """MLB.TV streaming provider using the public MLB Stats API for schedule data."""

    @property
    def name(self) -> str:
        return "mlb"

    @property
    def display_name(self) -> str:
        return "MLB.TV"

    async def get_schedule(self, date: datetime) -> list[Game]:
        """Fetch today's MLB schedule from the public Stats API."""
        date_str = date.strftime("%Y-%m-%d")

        # Run the synchronous statsapi call in a thread pool
        loop = asyncio.get_event_loop()
        try:
            raw_games = await loop.run_in_executor(
                None,
                lambda: statsapi.schedule(date=date_str),
            )
        except Exception:
            log.exception("Failed to fetch MLB schedule for %s", date_str)
            return []

        games: list[Game] = []
        for g in raw_games:
            try:
                status = _STATUS_MAP.get(
                    g.get("status", "Unknown"),
                    GameStatus.UNKNOWN,
                )

                # Parse game time
                game_datetime = datetime.fromisoformat(
                    g.get("game_datetime", date_str)
                )

                away_team = Team(
                    name=g.get("away_name", "Unknown"),
                    abbreviation=self._team_abbrev(g.get("away_name", "")),
                    score=g.get("away_score"),
                )
                home_team = Team(
                    name=g.get("home_name", "Unknown"),
                    abbreviation=self._team_abbrev(g.get("home_name", "")),
                    score=g.get("home_score"),
                )

                game = Game(
                    game_id=str(g.get("game_id", "")),
                    provider=self.name,
                    away_team=away_team,
                    home_team=home_team,
                    start_time=game_datetime,
                    status=status,
                    venue=g.get("venue_name", ""),
                    description=g.get("summary", ""),
                    extra={
                        "game_type": g.get("game_type", ""),
                        "series_status": g.get("series_status", ""),
                        "national_broadcasts": g.get("national_broadcasts", ""),
                        "away_probable_pitcher": g.get("away_probable_pitcher", ""),
                        "home_probable_pitcher": g.get("home_probable_pitcher", ""),
                        "current_inning": g.get("current_inning"),
                        "inning_state": g.get("inning_state", ""),
                    },
                )
                games.append(game)
            except Exception:
                log.exception("Failed to parse game: %s", g)
                continue

        # Sort: live games first, then by start time
        games.sort(key=lambda g: (
            0 if g.status == GameStatus.LIVE else
            1 if g.status == GameStatus.PRE_GAME else
            2 if g.status == GameStatus.SCHEDULED else
            3,
            g.start_time,
        ))

        return games

    async def get_game_status(self, game_id: str) -> GameStatus:
        """Poll a single game's status."""
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None,
                lambda: statsapi.schedule(game_id=int(game_id)),
            )
            if data:
                status_str = data[0].get("status", "Unknown")
                return _STATUS_MAP.get(status_str, GameStatus.UNKNOWN)
        except Exception:
            log.exception("Failed to get status for game %s", game_id)
        return GameStatus.UNKNOWN

    async def login(self, context: BrowserContext) -> bool:
        """
        Navigate to MLB.com login page and wait for user to complete login.
        The TUI will prompt the user to enter credentials in the browser.
        """
        page = await context.new_page()
        try:
            log.info("Navigating to MLB login page...")
            await page.goto(MLB_LOGIN_URL, wait_until="networkidle", timeout=30000)

            # Wait for the user to complete login — we detect success by
            # checking for redirect away from the login page, or presence
            # of authenticated elements.
            log.info("Waiting for login completion (up to 5 minutes)...")
            try:
                # Wait for navigation away from login page
                await page.wait_for_url(
                    lambda url: "login" not in url.lower(),
                    timeout=300_000,  # 5 minutes for manual login
                )
                log.info("Login appears successful — redirected from login page")
                return True
            except Exception:
                log.warning("Login timed out or failed")
                return False
        finally:
            await page.close()

    async def navigate_to_game(self, page: Page, game: Game) -> bool:
        """Navigate to a specific game's stream on MLB.TV."""
        url = MLB_TV_GAME_URL.format(game_id=game.game_id)
        log.info("Navigating to game: %s → %s", game.display_matchup, url)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for the video player to appear
            # MLB.TV uses a <video> element for playback
            try:
                await page.wait_for_selector(
                    "video, .mlbtv-media-player, [class*='player']",
                    timeout=15000,
                )
                log.info("Video player detected")
            except Exception:
                log.warning("Video player not found, page may still be loading")

            # Try to dismiss any overlays/modals that block playback
            await self._dismiss_overlays(page)

            # Try to click play if video isn't autoplaying
            await self._ensure_playing(page)

            return True
        except Exception:
            log.exception("Failed to navigate to game %s", game.game_id)
            return False

    async def is_authenticated(self, context: BrowserContext) -> bool:
        """Check if we have valid MLB.TV session cookies."""
        page = await context.new_page()
        try:
            await page.goto(MLB_TV_URL, wait_until="networkidle", timeout=20000)
            # Check if we're redirected to login or if we see authenticated content
            url = page.url.lower()
            if "login" in url or "signin" in url:
                return False

            # Look for indicators of being logged in
            try:
                await page.wait_for_selector(
                    "[class*='account'], [class*='user'], [class*='profile']",
                    timeout=5000,
                )
                return True
            except Exception:
                # No obvious auth indicator, but we're not on login page
                return True
        except Exception:
            log.exception("Auth check failed")
            return False
        finally:
            await page.close()

    # ── Private helpers ─────────────────────────────────────────

    async def _dismiss_overlays(self, page: Page) -> None:
        """Try to close common MLB.TV overlays and modals."""
        selectors = [
            "[class*='modal'] [class*='close']",
            "[class*='overlay'] [class*='close']",
            "[class*='dismiss']",
            "button[aria-label='Close']",
            "[class*='cookie'] button",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    await el.click()
                    log.info("Dismissed overlay: %s", sel)
            except Exception:
                pass

    async def _ensure_playing(self, page: Page) -> None:
        """Try to ensure video is actually playing."""
        try:
            # Check if video is paused and click play
            is_paused = await page.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    return video ? video.paused : null;
                }
            """)
            if is_paused:
                await page.evaluate("""
                    () => {
                        const video = document.querySelector('video');
                        if (video) video.play();
                    }
                """)
                log.info("Triggered video playback via JS")
        except Exception:
            # Try clicking a play button as fallback
            try:
                play_btn = page.locator(
                    "button[aria-label*='play' i], [class*='play-button'], [class*='PlayButton']"
                ).first
                if await play_btn.is_visible(timeout=2000):
                    await play_btn.click()
                    log.info("Clicked play button")
            except Exception:
                pass

    @staticmethod
    def _team_abbrev(team_name: str) -> str:
        """Convert full team name to abbreviation."""
        # Map of known MLB team names to abbreviations
        abbrevs: dict[str, str] = {
            "Arizona Diamondbacks": "ARI",
            "Atlanta Braves": "ATL",
            "Baltimore Orioles": "BAL",
            "Boston Red Sox": "BOS",
            "Chicago Cubs": "CHC",
            "Chicago White Sox": "CWS",
            "Cincinnati Reds": "CIN",
            "Cleveland Guardians": "CLE",
            "Colorado Rockies": "COL",
            "Detroit Tigers": "DET",
            "Houston Astros": "HOU",
            "Kansas City Royals": "KC",
            "Los Angeles Angels": "LAA",
            "Los Angeles Dodgers": "LAD",
            "Miami Marlins": "MIA",
            "Milwaukee Brewers": "MIL",
            "Minnesota Twins": "MIN",
            "New York Mets": "NYM",
            "New York Yankees": "NYY",
            "Oakland Athletics": "OAK",
            "Philadelphia Phillies": "PHI",
            "Pittsburgh Pirates": "PIT",
            "San Diego Padres": "SD",
            "San Francisco Giants": "SF",
            "Seattle Mariners": "SEA",
            "St. Louis Cardinals": "STL",
            "Tampa Bay Rays": "TB",
            "Texas Rangers": "TEX",
            "Toronto Blue Jays": "TOR",
            "Washington Nationals": "WSH",
        }
        return abbrevs.get(team_name, team_name[:3].upper())
