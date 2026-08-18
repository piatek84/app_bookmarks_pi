#!/usr/bin/env bash
# Tears down what start_pi.sh brings up: Funnel exposure and the app itself.
# Leaves Tailscale/tailscaled running (still needed for LAN/tailnet access).
set -euo pipefail

echo "==> Funnel"
tailscale serve --https=443 off || true

echo "==> bookmarks-pi service"
sudo systemctl stop bookmarks-pi

echo "==> Status"
sudo systemctl --no-pager -l status bookmarks-pi | head -5 || true
tailscale serve status
