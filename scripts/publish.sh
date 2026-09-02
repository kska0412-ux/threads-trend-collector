#!/usr/bin/env bash
# 生成済みの docs/index.html を GitHub Pages へ反映する。
# リモート未設定なら何もせず正常終了する（ローカル運用でも壊れないように）。
#
#   bash scripts/publish.sh [ログファイル]
#
# ログファイルを省略すると標準出力に出す。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${1:-}"

log() {
  local msg
  msg="$(date '+%Y-%m-%d %H:%M:%S') $*"
  if [ -n "$LOG" ]; then
    echo "$msg" >> "$LOG"
  else
    echo "$msg"
  fi
}

# git コマンドを実行し、出力をログに残す。
# 出力をログへ直接リダイレクトすると、ログが書けないときに
# git 自体が失敗して「変化なし」と誤判定されるため、こう分けている。
run() {
  local out status
  out="$("$@" 2>&1)"
  status=$?
  [ -n "$out" ] && log "$out"
  return $status
}

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  log "gitリポジトリではないため、公開はスキップしました。"
  exit 0
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  log "originが未設定のため、公開はスキップしました。"
  exit 0
fi

if [ ! -f docs/index.html ]; then
  log "docs/index.html がありません。先に build_html.py を実行してください。"
  exit 1
fi

if ! run git add docs/index.html; then
  log "git add に失敗しました。"
  exit 1
fi

if git diff --cached --quiet; then
  log "内容に変化がないため、公開はスキップしました。"
  exit 0
fi

if ! run git commit -m "収集結果を更新 $(date '+%Y-%m-%d %H:%M')"; then
  log "コミットに失敗しました。"
  exit 1
fi

# push の失敗は「認証切れ」と「通信できない」で対処が全く違う。
# 一律に gh auth login を促すと、回線が落ちていただけのときに遠回りさせる。
PUSH_OUT="$(git push origin HEAD 2>&1)"
PUSH_STATUS=$?
[ -n "$PUSH_OUT" ] && log "$PUSH_OUT"
if [ "$PUSH_STATUS" -ne 0 ]; then
  case "$PUSH_OUT" in
    *"Could not resolve host"*|*"unable to access"*|*"Connection refused"*|\
    *"Operation timed out"*|*"Network is unreachable"*|*"Could not connect"*)
      log "pushに失敗しました。ネットワークにつながっていません。"
      log "  コミットは手元に残っているので、回線が戻れば次回の実行でまとめて送られます。"
      ;;
    *"Authentication failed"*|*"Permission denied"*|*"403"*|*"could not read Username"*)
      log "pushに失敗しました。認証が切れています: gh auth login"
      ;;
    *)
      log "pushに失敗しました。上のメッセージを確認してください。"
      ;;
  esac
  exit 1
fi

log "公開しました。"
exit 0
