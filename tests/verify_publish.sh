#!/usr/bin/env bash
# publish.sh の公開判定を検証する。
# 本物の GitHub は使わず、ローカルにベアリポジトリを作って push 先にする。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
W="${TMPDIR:-/tmp}/ttc-publish-test-$$"
PASS=0; FAIL=0

check() {
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "  OK   $1";
  else FAIL=$((FAIL+1)); echo "  FAIL $1  → 期待 $3 / 実際 $2"; fi
}

mkdir -p "$W/work" "$W/remote"
export GIT_TEMPLATE_DIR="$W/tpl"; mkdir -p "$GIT_TEMPLATE_DIR"
git init -q --bare "$W/remote/repo.git"
cd "$W/work"
git init -q -b main
git config user.email test@example.com
git config user.name test
mkdir -p scripts docs
cp "$ROOT/scripts/publish.sh" scripts/
echo "<h1>v1</h1>" > docs/index.html
REMOTE="$W/remote/repo.git"
count() { git --git-dir="$REMOTE" rev-list --count HEAD 2>/dev/null || echo 0; }

bash scripts/publish.sh "$W/log" >/dev/null 2>&1
check "originが無ければスキップして正常終了" "$?" "0"

git remote add origin "$REMOTE"
bash scripts/publish.sh "$W/log" >/dev/null 2>&1
check "初回pushが成功する" "$?" "0"
check "リモートにコミットが1つ入る" "$(count)" "1"

bash scripts/publish.sh "$W/log" >/dev/null 2>&1
check "変化が無ければスキップする" "$?" "0"
check "リモートのコミットは増えない" "$(count)" "1"

echo "<h1>v2</h1>" > docs/index.html
bash scripts/publish.sh "$W/log" >/dev/null 2>&1
check "更新があればpushする" "$?" "0"
check "リモートのコミットが2つになる" "$(count)" "2"
check "リモートの中身が最新になる" "$(git --git-dir="$REMOTE" show HEAD:docs/index.html)" "<h1>v2</h1>"

# push できないときに成功と誤報しないこと（過去に踏んだ不具合）
git remote set-url origin "$W/nowhere.git"
echo "<h1>v3</h1>" > docs/index.html
bash scripts/publish.sh "$W/log" >/dev/null 2>&1
check "push失敗をエラーとして返す" "$?" "1"

git remote set-url origin "$REMOTE"
rm docs/index.html
bash scripts/publish.sh "$W/log" >/dev/null 2>&1
check "HTMLが無ければエラー" "$?" "1"

# ログが書けない場所でも、公開判定を誤らないこと（過去に踏んだ不具合）
echo "<h1>v4</h1>" > docs/index.html
bash scripts/publish.sh "/nonexistent-dir/log.txt" >/dev/null 2>&1
check "ログが書けなくてもpushは成功する" "$?" "0"
# push できなかった回のコミットはローカルに残り、次回まとめて送られる。
# そのため件数ではなく「最新の中身が届いているか」で確認する。
check "ログが書けなくてもリモートに最新が届く" "$(git --git-dir="$REMOTE" show HEAD:docs/index.html)" "<h1>v4</h1>"
check "保留されていた分もまとめて送られる" "$(count)" "4"

echo
echo "結果: $PASS pass / $FAIL fail"
rm -rf "$W"
[ "$FAIL" -eq 0 ]
