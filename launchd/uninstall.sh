#!/usr/bin/env bash
# Remove the GTMstack daily report launchd agent and its runtime copy.
# Leaves ~/.gtmstack/logs and any cookies in place.
set -euo pipefail
for LABEL in com.gtmstack.dailyreport com.gtmstack.monitorcatchup; do
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
done
rm -rf "$HOME/.gtmstack/app"
echo "removed dailyreport + monitorcatchup agents and ~/.gtmstack/app"
