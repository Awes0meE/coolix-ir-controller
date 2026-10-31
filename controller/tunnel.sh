#!/bin/sh
set -eu
controller_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$controller_dir/.."
umask 077
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
CLOUDFLARED_BIN=${CLOUDFLARED:-"$PWD/.tools/cloudflared/cloudflared"}
if [ ! -x "$CLOUDFLARED_BIN" ]; then
    CLOUDFLARED_BIN=$(command -v cloudflared || true)
fi
if [ -z "$CLOUDFLARED_BIN" ]; then
    echo 'Install cloudflared or set CLOUDFLARED to its executable path.' >&2
    exit 1
fi
exec "$CLOUDFLARED_BIN" tunnel --no-autoupdate run --token-file "$PWD/.runtime/controller/tunnel-token"
