#!/usr/bin/env bash
# 公開してはいけないファイルが GitHub に上がらないことを検証する。
#
# 守るもの:
#   .browser-profile/  Threads のログインCookie。漏れるとアカウントを乗っ取られる
#   data/              収集データ（HTMLに埋め込まれるので別途上げる必要がない）
#   node_modules/      依存物
#
# 防御は2段:
#   1. .gitignore で除外する
#   2. setup_github.sh が push 前に検出して中止する（1が壊れたときの保険）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
W="${TMPDIR:-/tmp}/ttc-safety-test-$$"
PASS=0; FAIL=0

check() {
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "  OK   $1";
  else FAIL=$((FAIL+1)); echo "  FAIL $1  → 期待 $3 / 実際 $2"; fi
}

# setup_github.sh と同じ判定式
danger_check() {
  local d
  d="$(git status --porcelain | grep -iE "browser-profile|Cookies|Login Data|posts\.json|raw_latest|node_modules|\.env" || true)"
  [ -n "$d" ] && return 1 || return 0
}

mkdir -p "$W"; cd "$W"
export GIT_TEMPLATE_DIR="$W/tpl"; mkdir -p "$GIT_TEMPLATE_DIR"
git init -q -b main

# 本番と同じ構造を作る。ログインCookieに相当するファイルも実際に置く。
mkdir -p .browser-profile/Default data docs scripts config node_modules/playwright
echo "SESSION_COOKIE" > .browser-profile/Default/Cookies
echo "SECRET" > ".browser-profile/Default/Login Data"
echo '{"posts":{}}' > data/posts.json
echo '{}' > data/raw_latest.json
echo "<h1>page</h1>" > docs/index.html
echo "code" > scripts/collect.py
echo "{}" > config/keywords.json
echo "lib" > node_modules/playwright/index.js

cp "$ROOT/.gitignore" .
git add -A

check "ログインCookieは追跡されない" "$(git check-ignore -q .browser-profile/Default/Cookies; echo $?)" "0"
check "収集データは追跡されない" "$(git check-ignore -q data/posts.json; echo $?)" "0"
check "node_modules は追跡されない" "$(git check-ignore -q node_modules/playwright/index.js; echo $?)" "0"
check "公開するHTMLは追跡される" "$(git check-ignore -q docs/index.html; echo $?)" "1"
check "スクリプトは追跡される" "$(git check-ignore -q scripts/collect.py; echo $?)" "1"

STAGED="$(git status --porcelain | awk '{print $NF}' | sort | tr '\n' ' ')"
check "コミット対象は安全なものだけ" "$STAGED" ".gitignore config/keywords.json docs/index.html scripts/collect.py "

danger_check
check "正常時は公開前チェックを通過する" "$?" "0"

# .gitignore が失われた事故を想定する
git rm -r --cached . -q
rm .gitignore
git add -A
danger_check
check "gitignoreが壊れたら公開前チェックが止める" "$?" "1"

cd /
rm -rf "$W"
echo
echo "結果: $PASS pass / $FAIL fail"
[ "$FAIL" -eq 0 ]
