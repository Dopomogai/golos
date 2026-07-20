"""py2app build for golos.app — run via build_app.sh."""

import sys

from setuptools import setup

# modulegraph walks the AST of every included module; mlx ships some deeply
# nested generated code that exceeds the default recursion limit.
sys.setrecursionlimit(20000)

APP = ["app_launcher.py"]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "golos.icns",
    "resources": ["assets/glyph.png"],
    "packages": [
        "dictate", "dictate_core", "mlx_whisper", "mlx", "sounddevice",
        "_sounddevice_data", "httpx", "httpcore", "h11", "certifi",
        "toml", "numpy",
    ],
    "includes": [
        "objc", "AppKit", "Foundation", "Quartz", "CoreFoundation",
        "ApplicationServices", "AVFoundation", "PyObjCTools",
    ],
    # Heavy transitive deadweight modulegraph drags in via optional imports
    # (transformers/huggingface chains). None of it is used at runtime.
    "excludes": [
        "torch", "torchgen", "numba", "scipy", "sympy", "matplotlib",
        "pandas", "PIL", "Pillow", "IPython", "jupyter", "notebook",
        "triton", "tvm", "tensorflow", "jax", "jaxlib", "keras",
        "sklearn", "statsmodels", "seaborn", "plotly", "bokeh",
    ],
    "plist": {
        "CFBundleName": "golos",
        "CFBundleDisplayName": "golos",
        "CFBundleIdentifier": "com.softprom.golos",
        "CFBundleShortVersionString": "0.2.0",
        "LSUIElement": True,  # accessory app: no dock icon
        "NSMicrophoneUsageDescription":
            "golos records your voice while you hold the hotkey and turns it into text.",
        "NSAppleEventsUsageDescription":
            "golos reads the current browser tab / Finder selection to give the formatter context.",
    },
}

setup(app=APP, options={"py2app": OPTIONS})
