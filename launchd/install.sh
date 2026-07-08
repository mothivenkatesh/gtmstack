#!/usr/bin/env bash
# Install the GTMstack daily report as a macOS launchd agent (runs 09:00 IST).
#
# macOS will not let a launchd job read ~/Documents (it is TCC-protected), so we
# copy the runtime to ~/.gtmstack/app (not protected) and run from there. That
# avoids any Full Disk Access prompt. The repo stays your dev copy; re-run this
# script after you change api/ or daily_report.py to re-sync.
#
# The agent only fires when the Mac is awake and you are logged in.
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
# Prefer a dedicated venv OUTSIDE ~/Documents (TCC-safe for launchd) if present;
# create it with:  python3 -m venv ~/.gtmstack/venv && ~/.gtmstack/venv/bin/pip install requests curl_cffi
PY="$(python3 -c 'import sys; print(sys.executable)')"
[ -x "$HOME/.gtmstack/venv/bin/python" ] && PY="$HOME/.gtmstack/venv/bin/python"
LABEL="com.gtmstack.dailyreport"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CATCHUP_LABEL="com.gtmstack.monitorcatchup"
CATCHUP_PLIST="$HOME/Library/LaunchAgents/$CATCHUP_LABEL.plist"
APP="$HOME/.gtmstack/app"
LOGDIR="$HOME/.gtmstack/logs"

mkdir -p "$APP" "$LOGDIR" "$HOME/Library/LaunchAgents"

# Sync code into the non-protected runtime dir.
rm -rf "$APP/api"
cp -R "$PROJECT/api" "$APP/api"
cp "$PROJECT/daily_report.py" "$APP/daily_report.py"
# Carry creds if a .env exists (gitignored; never committed). The job reads its
# own dir's .env, so this is how DATABASE_URL / cookies / model keys travel.
[ -f "$PROJECT/.env" ] && cp "$PROJECT/.env" "$APP/.env" || true

# Version + env manifest so a run can tell if the runtime drifted from the repo.
# Stamps a hash of the copied code AND the copied .env: the version stamp must
# detect ENV drift too, since a new secret needs a re-install to travel here.
{
  echo "synced_from=$PROJECT"
  echo "code_hash=$(find "$APP/api" "$APP/daily_report.py" -type f -exec shasum {} \; | shasum | cut -d' ' -f1)"
  echo "env_hash=$([ -f "$APP/.env" ] && shasum "$APP/.env" | cut -d' ' -f1 || echo none)"
} > "$APP/MANIFEST"

# Job 1: the full daily run (reports + competitive monitor) at 09:00 IST.
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$APP/daily_report.py</string>
  </array>
  <key>WorkingDirectory</key><string>$APP</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>9</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$LOGDIR/daily.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/daily.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
EOF

# Job 2: the 13:00 IST catch-up. Runs ONLY the monitor and only if the 9am run
# was missed (the Mac was asleep or logged out); the marker check makes it a
# no-op otherwise. This is the local safety net; the hosted Vercel watchdog is
# the alarm for when the Mac is off entirely.
cat > "$CATCHUP_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$CATCHUP_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$APP/daily_report.py</string>
    <string>--catchup</string>
  </array>
  <key>WorkingDirectory</key><string>$APP</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>13</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$LOGDIR/daily.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/daily.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"
launchctl unload "$CATCHUP_PLIST" 2>/dev/null || true
launchctl load -w "$CATCHUP_PLIST"

echo "installed: $LABEL + $CATCHUP_LABEL"
echo "  python : $PY"
echo "  runtime: $APP   (copied from $PROJECT)"
echo "  when   : 09:00 IST full run + 13:00 IST monitor catch-up (Mac awake + logged in)"
echo "  log    : $LOGDIR/daily.log"
echo
echo "deps: that python needs the repo deps -> $PY -m pip install -r $PROJECT/requirements.txt"
echo "test now: launchctl start $LABEL && tail -f $LOGDIR/daily.log"
echo "uninstall: $PROJECT/launchd/uninstall.sh"
