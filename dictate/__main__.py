"""CLI entry: `python -m dictate` (dev) and the py2app launcher both call main().

Loads ~/.golos/config.toml (migrating from ~/.dictate on first run) and hands
off to run_app(), which owns the NSApplication run loop until quit.
"""

import sys

from .config import configure_frozen_ca, load_config
from .diagnostics import configure_logging
from .app import run_app


def main():
    """Configure logging, load config, enter the AppKit run loop (blocks)."""
    configure_logging()
    configure_frozen_ca()
    cfg = load_config()
    run_app(cfg)


if __name__ == "__main__":
    sys.exit(main())
