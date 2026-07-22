"""py2app build for golos.app — run via build_app.sh (not `python setup.py` alone).

Platform: macOS only (AppKit/Quartz/AVFoundation includes). Excludes list
keeps optional ML/data-science transitive deps out of the bundle so DMG size
stays manageable; packages/includes list is the allow-set for what ships.
"""

import os
import sys

import certifi
from setuptools import setup

# modulegraph walks the AST of every included module; mlx ships some deeply
# nested generated code that exceeds the default recursion limit.
sys.setrecursionlimit(20000)

APP = ["app_launcher.py"]
INCLUDE_MLX = os.environ.get("GOLOS_INCLUDE_MLX", "1") != "0"
APP_VERSION = os.environ.get("GOLOS_VERSION", "0.3.3")
try:
    _major, _minor, _patch = (int(part) for part in APP_VERSION.split(".", 2))
    _default_build = str((_major * 10_000) + (_minor * 100) + _patch)
except (TypeError, ValueError):
    _default_build = "303"
APP_BUILD = os.environ.get("GOLOS_BUILD", _default_build)
PACKAGES = [
    "dictate", "dictate_core", "sounddevice", "_sounddevice_data",
    "httpx", "httpcore", "h11", "certifi", "toml", "numpy",
]
if INCLUDE_MLX:
    PACKAGES.extend(["mlx_whisper", "mlx"])

EXCLUDES = [
    "torch", "torchgen", "numba", "scipy", "sympy", "matplotlib",
    "pandas", "PIL", "Pillow", "IPython", "jupyter", "notebook",
    "triton", "tvm", "tensorflow", "jax", "jaxlib", "keras",
    "sklearn", "statsmodels", "seaborn", "plotly", "bokeh",
    "tkinter", "_tkinter",
]
if not INCLUDE_MLX:
    EXCLUDES.extend(["mlx", "mlx_whisper", "huggingface_hub"])

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "golos.icns",
    # config.toml contains no credentials. It is the clean-install seed copied
    # to ~/.golos/config.toml on first launch; all later writes stay there.
    "resources": ["assets/glyph.png", "config.toml", certifi.where()],
    "packages": PACKAGES,
    "includes": [
        "objc", "AppKit", "Foundation", "Quartz", "CoreFoundation",
        "ApplicationServices", "AVFoundation", "PyObjCTools",
    ],
    # Heavy transitive deadweight modulegraph drags in via optional imports
    # (transformers/huggingface chains). None of it is used at runtime.
    "excludes": EXCLUDES,
    "plist": {
        "CFBundleName": "golos",
        "CFBundleDisplayName": "golos",
        "CFBundleIdentifier": "com.softprom.golos",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_BUILD,
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,  # accessory app: no dock icon
        "NSMicrophoneUsageDescription":
            "golos records your voice while you hold the hotkey and turns it into text.",
        "NSAppleEventsUsageDescription":
            "golos reads the current browser tab / Finder selection to give the formatter context.",
    },
}

setup(app=APP, options={"py2app": OPTIONS})
