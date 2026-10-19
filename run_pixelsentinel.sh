#!/bin/bash

set -u

umask 077


SCRIPT_DIR="$(
    cd "$(dirname "$0")" || exit 1
    pwd
)"

PROJECT_DIR="$SCRIPT_DIR"

VENV_DIR="$PROJECT_DIR/pixelsentinel_env"

PYTHON="$VENV_DIR/bin/python3.14"

PIXELSENTINEL="$PROJECT_DIR/pixelsentinel.py"


print_error() {
    echo "Error: $1" >&2
    exit 1
}


if [ ! -x "$PYTHON" ]; then
    print_error \
        "Virtual environment Python was not found."
fi


if [ ! -f "$PIXELSENTINEL" ]; then
    print_error \
        "pixelsentinel.py was not found."
fi


cd "$PROJECT_DIR" \
    || print_error \
        "Unable to enter PixelSentinel directory."


echo "Running PixelSentinel..."


exec "$PYTHON" \
    "$PIXELSENTINEL"