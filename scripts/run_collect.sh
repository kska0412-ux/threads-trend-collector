#!/usr/bin/env bash
# 収集 → HTML生成 → GitHub Pages へ公開 まで一息で実行する。
# launchd から1日3回呼ばれる。手動で実行しても同じことが起きる。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

LOG="logs/collect.log"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

log "===== 開始 ====="

if ! /usr/bin/env python3 scripts/collect.py >> "$LOG" 2>&1; then
  log "収集に失敗。ページは更新しません。"
  exit 1
fi

if ! /usr/bin/env python3 scripts/build_html.py >> "$LOG" 2>&1; then
  log "HTML生成に失敗。"
  exit 1
fi

# --- GitHub Pages へ公開 ---
if ! bash scripts/publish.sh "$LOG"; then
  log "公開に失敗しました。"
  exit 1
fi

log "===== 完了 ====="
