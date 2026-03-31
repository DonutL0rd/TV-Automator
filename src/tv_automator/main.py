"""TV-Automator entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import uvicorn

from tv_automator.config import Config


def setup_logging(data_dir: Path) -> None:
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

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    config_path = None
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])

    config = Config(config_path=config_path)
    setup_logging(config.data_dir)

    log = logging.getLogger(__name__)
    log.info("Starting TV-Automator web server on port 5000...")

    from tv_automator.web.app import app

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
