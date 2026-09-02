#!/usr/bin/env bash
# 収集 → HTML生成 → GitHub Pages へ公開 まで一息で実行する。
# launchd から1日3回呼ばれる。手動で実行しても同じことが起きる。
#
# 自動実行を落とさないための仕掛けが2つ入っている:
#   1. 排他ロック  同じプロファイルを2つのChromeで開けないため、実行が重なると
#                  後発が3分待って必ず落ちる。重なったら後発は静かに譲る。
#   2. 再試行      起動失敗は一時的なことが多い。次のスロットまで最大8時間
#                  空くので、その場で間を置いて掛け直す。
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

# 失敗したときに掛け直すまでの秒数。空にすると再試行しない。
# テストから短い値に差し替えられるようにしてある。
RETRY_WAITS="${TTC_RETRY_WAITS:-600 1800}"

# --- 排他ロック -------------------------------------------------------
# mkdir は「あれば失敗する」が1操作で決まるので、取り合いになっても
# どちらか片方しか通らない。ファイル作成だと確認と作成の間に割り込まれる。
LOCK="logs/collect.lock"

take_lock() {
  if mkdir "$LOCK" 2>/dev/null; then
    echo $$ > "$LOCK/pid"
    return 0
  fi
  return 1
}

if ! take_lock; then
  OTHER="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [ -n "$OTHER" ] && kill -0 "$OTHER" 2>/dev/null; then
    log "先行する収集が実行中（PID ${OTHER}）のため、今回は何もしません。"
    exit 0
  fi
  # 前回が強制終了などで後片付けできなかった跡。放置すると二度と動かない
  log "前回の収集が異常終了した跡（PID ${OTHER:-不明}）を片付けます。"
  rm -rf "$LOCK"
  if ! take_lock; then
    log "ロックを取得できませんでした。今回は何もしません。"
    exit 1
  fi
fi
trap 'rm -rf "$LOCK"' EXIT
# ----------------------------------------------------------------------

log "===== 開始 ====="

# --- 収集（失敗したら間を置いて掛け直す） ---
# -u を付けて出力のバッファリングを切る。付けないと数キロバイト溜まるまで
# ログに書き出されず、動いているのに止まって見える。
attempt=1
collected=0
for wait in $RETRY_WAITS ""; do
  if /usr/bin/env python3 -u scripts/collect.py >> "$LOG" 2>&1; then
    collected=1
    break
  fi
  if [ -z "$wait" ]; then
    log "収集に $attempt 回失敗。ページは更新しません。"
    break
  fi
  log "収集に失敗（$attempt 回目）。${wait}秒後に掛け直します。"
  sleep "$wait"
  attempt=$((attempt + 1))
done

if [ "$collected" -ne 1 ]; then
  exit 1
fi
if [ "$attempt" -gt 1 ]; then
  log "$attempt 回目で収集に成功しました。"
fi

if ! /usr/bin/env python3 -u scripts/build_html.py >> "$LOG" 2>&1; then
  log "HTML生成に失敗。"
  exit 1
fi

# --- GitHub Pages へ公開 ---
if ! bash scripts/publish.sh "$LOG"; then
  log "公開に失敗しました。"
  exit 1
fi

log "===== 完了 ====="
