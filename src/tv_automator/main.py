"""TV-Automator entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from tv_automator.config import Config


def setup_logging(data_dir: Path) -> None:
    """Configure logging to both file and stderr."""
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "tv-automator.log"),
            logging.StreamHandler(sys.stderr),
        ],
    )

    # Quiet down noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)


def main() -> None:
    """Launch the TV-Automator TUI."""
    # Load configuration
    config_path = None
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])

    config = Config(config_path=config_path)
    setup_logging(config.data_dir)

    log = logging.getLogger(__name__)
    log.info("Starting TV-Automator...")

    # Import and run the TUI app
    from tv_automator.tui.app import TVAutomatorApp

    app = TVAutomatorApp(config=config)
    app.run()


if __name__ == "__main__":
    main()
