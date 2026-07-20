"""Entry point: python -m dictate"""

import logging
import sys

from .config import load_config
from .app import run_app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    run_app(cfg)


if __name__ == "__main__":
    sys.exit(main())
