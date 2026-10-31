#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export ARDUINO_DIRECTORIES_DATA="$PROJECT_ROOT/.arduino/data"
export ARDUINO_DIRECTORIES_DOWNLOADS="$PROJECT_ROOT/.arduino/downloads"
export ARDUINO_DIRECTORIES_USER="$PROJECT_ROOT/.arduino/user"
export ARDUINO_BUILD_CACHE_PATH="$PROJECT_ROOT/.arduino/build-cache"

ARDUINO_CLI_BIN=${ARDUINO_CLI:-"$PROJECT_ROOT/.tools/arduino-cli/arduino-cli"}
if [ ! -x "$ARDUINO_CLI_BIN" ]; then
    ARDUINO_CLI_BIN=$(command -v arduino-cli || true)
fi
if [ -z "$ARDUINO_CLI_BIN" ]; then
    echo 'Install Arduino CLI or set ARDUINO_CLI to its executable path.' >&2
    exit 1
fi
exec "$ARDUINO_CLI_BIN" "$@"
