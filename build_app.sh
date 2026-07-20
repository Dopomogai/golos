#!/bin/bash
# Build dist/dictate.app with py2app.
set -euo pipefail
cd "$(dirname "$0")"

# mlx is a PEP 420 namespace package (no __init__.py); py2app's package
# recipe can't bootstrap those. A harmless empty __init__.py in the venv
# copy makes it a regular package so the FULL tree (nn/, lib/mlx.metallib,
# core.so) is bundled.
MLX_PKG=.venv/lib/python3.13/site-packages/mlx
[ -f "$MLX_PKG/__init__.py" ] || touch "$MLX_PKG/__init__.py"

# py2app errors when distribution.install_requires is non-empty — setuptools
# fills it from pyproject.toml's [project] dependencies. Hide pyproject.toml
# for the duration of the build (restored even on failure).
mv pyproject.toml /tmp/dictate_pyproject.toml.$$
restore_pyproject() { mv /tmp/dictate_pyproject.toml.$$ pyproject.toml; }
trap restore_pyproject EXIT

rm -rf build dist
.venv/bin/python setup.py py2app 2>&1 | tail -20
echo "---"
du -sh dist/golos.app
echo "built dist/golos.app"
