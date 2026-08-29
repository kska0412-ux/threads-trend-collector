#!/usr/bin/env bash
# 1日3回（7時/13時/21時）の自動収集を登録する。
#
#   bash scripts/install_launchd.sh
#
# 解除は scripts/uninstall_launchd.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.kameda.threads-trend-collector"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__ROOT__|$ROOT|g" "$ROOT/config/launchd/$LABEL.plist" > "$DEST"

launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"

echo "登録しました: $DEST"
echo "朝7時 / 昼13時 / 夜21時 に自動収集されます。"
echo
echo "確認:   launchctl list | grep $LABEL"
echo "今すぐ実行: launchctl start $LABEL"
echo "ログ:     tail -f $ROOT/logs/collect.log"
