#!/bin/sh
set -eu

AGENT_EXECUTABLE="${1:?Pass the absolute path to bbc-course-agent}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST="$PLIST_DIR/com.clearenglish.bbc-course-agent.plist"
mkdir -p "$PLIST_DIR"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.clearenglish.bbc-course-agent</string>
  <key>ProgramArguments</key><array><string>$AGENT_EXECUTABLE</string><string>serve</string></array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
EOF
launchctl bootout gui/$(id -u) "$PLIST" 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PLIST"
echo "Installed local Clear English Speaking agent. Its editable in-app schedule runs while your Mac is awake."
