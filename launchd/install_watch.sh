#!/bin/bash
# Schedule GTMstack watches so the agent works while nobody is looking.
# This is the difference between a toolkit and a product: without it, the app
# only ever does work when a human clicks.
#
# Runs every 6 hours. Delivery is idempotent, so an extra fire is a no-op.
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(python3 -c 'import sys; print(sys.executable)')"
[ -x "$PROJECT/.venv/bin/python" ] && PY="$PROJECT/.venv/bin/python"
[ -x "$HOME/.gtmstack/venv/bin/python" ] && PY="$HOME/.gtmstack/venv/bin/python"

LABEL="com.gtmstack.watch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.gtmstack/watch.log"
mkdir -p "$HOME/.gtmstack"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$PROJECT/watch_run.py</string></array>
  <key>StartInterval</key><integer>21600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>WorkingDirectory</key><string>$PROJECT</string>
</dict></plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Scheduled: $LABEL (every 6h). Log: $LOG"
echo "Check it:  python $PROJECT/watch_run.py --status"
echo "Stop it:   launchctl unload $PLIST && rm $PLIST"
