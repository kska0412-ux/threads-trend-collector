#!/usr/bin/env bash
# 収集 → HTML生成 → GitHub Pages へ公開 まで一息で実行する。
# launchd から1日3回呼ばれる。手動で実行しても同じことが起きる。
set -uo pipefail

# 収集は数分かかる。途中でスリープに入ると中断されるため、
# 実行中だけ起きたままにする（終了すれば元の設定に戻る）。
if [ -z "${TTC_AWAKE:-}" ] && [ -x /usr/bin/caffeinate ]; then
  export TTC_AWAKE=1
  # bash 経由で呼ぶ。ファイルに実行権限が無くても動くようにするため。
  exec /usr/bin/caffeinate -i -s /bin/bash "${BASH_SOURCE[0]}" "$@"
fi

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
