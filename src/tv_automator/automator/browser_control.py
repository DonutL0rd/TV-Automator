"""Browser automation controller using Playwright + Google Chrome."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page

if TYPE_CHECKING:
    from tv_automator.config import Config
    from tv_automator.providers.base import Game, StreamingProvider

log = logging.getLogger(__name__)


class BrowserController:
    """
    Manages a persistent Google Chrome browser instance.

    Responsibilities:
    - Launch Chrome with kiosk flags, connected to the X11 display
    - Maintain a persistent browser context with saved cookies
    - Provide pages to providers for login/navigation
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._active_page: Page | None = None

    # ── Lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the browser."""
        log.info("Starting browser controller...")
        self._playwright = await async_playwright().start()

        chrome_path = self._config.browser.get("chrome_path")

        # Build launch args
        args = list(self._config.chrome_args)
        args.extend([
            "--no-sandbox",
            "--disable-gpu-sandbox",
            "--start-fullscreen",
        ])

        launch_kwargs = {
            "args": args,
            "ignore_default_args": ["--enable-automation"],
            "headless": False,  # We need a visible browser for HDMI output
        }

        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path

        # Try Chrome first, fall back to Chromium
        try:
            self._browser = await self._playwright.chromium.launch(
                channel="chrome",
                **launch_kwargs,
            )
            log.info("Launched Google Chrome")
        except Exception:
            log.warning("Chrome not found, falling back to Chromium (DRM may not work)")
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            log.info("Launched Chromium")

        # Create or restore browser context
        await self._create_context()
        log.info("Browser controller ready")

    async def stop(self) -> None:
        """Shut down the browser."""
        log.info("Stopping browser controller...")
        if self._active_page:
            try:
                await self._active_page.close()
            except Exception:
                pass
            self._active_page = None

        if self._context:
            # Save cookies before closing
            await self._save_cookies()
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        log.info("Browser controller stopped")

    @property
    def is_running(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    @property
    def context(self) -> BrowserContext | None:
        return self._context

    @property
    def active_page(self) -> Page | None:
        return self._active_page

    # ── Provider operations ─────────────────────────────────────

    async def login(self, provider: StreamingProvider) -> bool:
        """Perform login for a provider."""
        if not self._context:
            log.error("Browser not started")
            return False

        log.info("Starting login for %s...", provider.display_name)
        result = await provider.login(self._context)

        if result:
            await self._save_cookies()
            log.info("Login successful, cookies saved")
        else:
            log.warning("Login failed for %s", provider.display_name)

        return result

    async def is_authenticated(self, provider: StreamingProvider) -> bool:
        """Check if we're authenticated with a provider."""
        if not self._context:
            return False
        return await provider.is_authenticated(self._context)

    async def play_game(self, provider: StreamingProvider, game: Game) -> bool:
        """Navigate to and play a specific game."""
        if not self._context:
            log.error("Browser not started")
            return False

        # Create or reuse the active page
        if self._active_page and not self._active_page.is_closed():
            page = self._active_page
        else:
            page = await self._context.new_page()
            self._active_page = page

        # Set viewport to match display resolution
        res = self._config.display.get("resolution", "1920x1080")
        width, height = (int(x) for x in res.split("x"))
        await page.set_viewport_size({"width": width, "height": height})

        log.info("Playing: %s", game.summary)
        result = await provider.navigate_to_game(page, game)

        if result:
            # Enter fullscreen via F11 key
            try:
                await page.keyboard.press("F11")
            except Exception:
                pass
            log.info("Game is now playing")
        else:
            log.warning("Failed to start game playback")

        return result

    async def stop_playback(self) -> None:
        """Stop current playback and show a blank page."""
        if self._active_page and not self._active_page.is_closed():
            try:
                await self._active_page.goto("about:blank")
                log.info("Playback stopped")
            except Exception:
                pass

    @property
    def now_playing_url(self) -> str | None:
        """Get the URL of what's currently playing."""
        if self._active_page and not self._active_page.is_closed():
            url = self._active_page.url
            return url if url != "about:blank" else None
        return None

    # ── Cookie management ───────────────────────────────────────

    async def _create_context(self) -> None:
        """Create a browser context, restoring cookies if available."""
        if not self._browser:
            return

        cookie_file = self._cookie_path()

        # Create context with realistic browser settings
        self._context = await self._browser.new_context(
            viewport=None,  # Use browser window size
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="dark",
        )

        # Restore cookies if they exist
        if cookie_file.exists():
            try:
                with open(cookie_file) as f:
                    cookies = json.load(f)
                await self._context.add_cookies(cookies)
                log.info("Restored %d cookies from %s", len(cookies), cookie_file)
            except Exception:
                log.warning("Failed to restore cookies")

    async def _save_cookies(self) -> None:
        """Persist cookies to disk."""
        if not self._context:
            return

        cookie_file = self._cookie_path()
        try:
            cookies = await self._context.cookies()
            cookie_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cookie_file, "w") as f:
                json.dump(cookies, f, indent=2)
            log.info("Saved %d cookies to %s", len(cookies), cookie_file)
        except Exception:
            log.exception("Failed to save cookies")

    def _cookie_path(self) -> Path:
        return self._config.cookie_dir / "browser_cookies.json"
