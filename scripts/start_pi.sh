#!/usr/bin/env bash
# Brings up bookmarks-pi + Tailscale Funnel on the Pi. Safe to re-run --
# every step only acts if that piece isn't already up.
set -euo pipefail

APP_PORT=8001

echo "==> bookmarks-pi service"
sudo systemctl start bookmarks-pi
sudo systemctl --no-pager -l status bookmarks-pi | head -5

echo "==> Tailscale"
if ! tailscale status >/dev/null 2>&1; then
    echo "not running, starting..."
    sudo tailscale up
else
    echo "already up."
fi

echo "==> Funnel on :${APP_PORT}"
if tailscale serve status 2>/dev/null | grep -q "Funnel on"; then
    echo "already active."
else
    echo "enabling..."
    sudo tailscale funnel --bg "http://localhost:${APP_PORT}"
fi

echo "==> Status"
tailscale serve status
