"""py2app entry point (absolute imports only — the bundle's bootstrapped
__main__.py is not inside the dictate package, so `from .config import …`
would fail there). Normal runs use `python -m dictate` instead."""

import sys

from dictate.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
