#!/bin/bash
# Build dist/golos.app with py2app.
set -euo pipefail
cd "$(dirname "$0")"

GOLOS_VENV="${GOLOS_VENV:-.venv}"
GOLOS_INCLUDE_MLX="${GOLOS_INCLUDE_MLX:-1}"
GOLOS_ARCH="${GOLOS_ARCH:-}"
GOLOS_DIST_DIR="${GOLOS_DIST_DIR:-dist}"
GOLOS_BUILD_DIR="${GOLOS_BUILD_DIR:-build}"
# GOLOS_VERSION / GOLOS_BUILD are read by setup.py for isolated patch/RC builds.

validate_output_dir() {
    case "$1" in
        ""|/|"$HOME"|"$(pwd)")
            echo "refusing unsafe build output directory: $1" >&2
            exit 2
            ;;
    esac
}
validate_output_dir "$GOLOS_DIST_DIR"
validate_output_dir "$GOLOS_BUILD_DIR"

run_python() {
    if [ -n "$GOLOS_ARCH" ]; then
        arch -"$GOLOS_ARCH" "$GOLOS_VENV/bin/python" "$@"
    else
        "$GOLOS_VENV/bin/python" "$@"
    fi
}

# mlx is a PEP 420 namespace package (no __init__.py); py2app's package
# recipe can't bootstrap those. A harmless empty __init__.py in the venv
# copy makes it a regular package so the FULL tree (nn/, lib/mlx.metallib,
# core.so) is bundled.
if [ "$GOLOS_INCLUDE_MLX" = "1" ]; then
    MLX_PKG=$(run_python -c \
        'import mlx, pathlib; print(pathlib.Path(next(iter(mlx.__path__))))')
    [ -f "$MLX_PKG/__init__.py" ] || touch "$MLX_PKG/__init__.py"
fi

# py2app errors when distribution.install_requires is non-empty — setuptools
# fills it from pyproject.toml's [project] dependencies. Hide pyproject.toml
# for the duration of the build (restored even on failure).
mv pyproject.toml /tmp/dictate_pyproject.toml.$$
restore_pyproject() {
    if [ -f /tmp/dictate_pyproject.toml.$$ ]; then
        mv /tmp/dictate_pyproject.toml.$$ pyproject.toml
    fi
}
trap restore_pyproject EXIT

# Keep previously built DMGs so architecture builds can run sequentially.
# Override both dirs for an isolated smoke build while another app copy runs.
rm -rf "$GOLOS_BUILD_DIR" "$GOLOS_DIST_DIR/golos.app"
mkdir -p "$GOLOS_DIST_DIR"
if [ -n "$GOLOS_ARCH" ]; then
    GOLOS_INCLUDE_MLX="$GOLOS_INCLUDE_MLX" \
        run_python setup.py py2app "--arch=$GOLOS_ARCH" \
        "--bdist-base=$GOLOS_BUILD_DIR" "--dist-dir=$GOLOS_DIST_DIR" \
        2>&1 | tail -20
else
    GOLOS_INCLUDE_MLX="$GOLOS_INCLUDE_MLX" run_python setup.py py2app \
        "--bdist-base=$GOLOS_BUILD_DIR" "--dist-dir=$GOLOS_DIST_DIR" \
        2>&1 | tail -20
fi
echo "---"
du -sh "$GOLOS_DIST_DIR/golos.app"
echo "built $GOLOS_DIST_DIR/golos.app"
