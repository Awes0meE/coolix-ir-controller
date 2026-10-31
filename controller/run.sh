#!/bin/sh
set -eu
controller_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$controller_dir/.."
umask 077
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ -f .runtime/controller/service.env ]; then
    . .runtime/controller/service.env
fi
exec /usr/bin/caffeinate -i "$PWD/.venv/bin/python" -m uvicorn controller.server:app --host 127.0.0.1 --port 8768 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
