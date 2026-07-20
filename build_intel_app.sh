#!/bin/bash
# Build the cloud-only Intel edition. MLX is intentionally omitted; users on
# Intel Macs use OpenRouter transcription and formatting.
set -euo pipefail
cd "$(dirname "$0")"

INTEL_PYTHON="${GOLOS_INTEL_PYTHON:-/usr/local/bin/python3-intel64}"
INTEL_VENV="${GOLOS_INTEL_VENV:-.venv-intel}"

if [ ! -x "$INTEL_PYTHON" ]; then
    echo "Intel Python not found: $INTEL_PYTHON" >&2
    echo "Set GOLOS_INTEL_PYTHON to a Python 3.11+ x86_64 interpreter." >&2
    exit 1
fi

if [ ! -x "$INTEL_VENV/bin/python" ]; then
    arch -x86_64 "$INTEL_PYTHON" -m venv "$INTEL_VENV"
fi

arch -x86_64 "$INTEL_VENV/bin/python" -m pip install \
    --disable-pip-version-check -r requirements-cloud.txt

GOLOS_VENV="$INTEL_VENV" GOLOS_INCLUDE_MLX=0 GOLOS_ARCH=x86_64 \
    ./build_app.sh

file dist/golos.app/Contents/MacOS/golos
echo "built cloud-only Intel dist/golos.app"
