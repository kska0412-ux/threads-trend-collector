#!/usr/bin/env bash
# 自動収集の登録を解除する。
set -euo pipefail

LABEL="com.kameda.threads-trend-collector"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl unload "$DEST" 2>/dev/null || true
rm -f "$DEST"
echo "解除しました: $LABEL"
