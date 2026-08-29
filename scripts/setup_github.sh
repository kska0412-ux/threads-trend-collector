#!/usr/bin/env bash
# GitHub Pages で公開するための初期設定。最初に1回だけ実行する。
#
#   bash scripts/setup_github.sh
#
# やること:
#   1. gitリポジトリを作る
#   2. ログインセッションが混ざっていないか確認する
#   3. GitHub にリポジトリを作って push する
#   4. GitHub Pages を有効にする
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REPO_NAME="${1:-threads-trend-collector}"

echo "== 1. 前提の確認 =="
command -v gh >/dev/null || { echo "gh コマンドがありません: brew install gh"; exit 1; }
if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub の認証が切れています。先に次を実行してください:"
  echo "  gh auth login"
  exit 1
fi
echo "  OK: gh 認証済み"

echo "== 2. git リポジトリを用意 =="
if [ -d .git ]; then
  echo "  既にリポジトリがあります。そのまま使います。"
else
  git init -q -b main
  echo "  作成しました。"
fi

git add -A

echo "== 3. 危険なファイルが混ざっていないか確認 =="
DANGER=$(git status --porcelain | grep -iE "browser-profile|Cookies|posts\.json|node_modules|\.env" || true)
if [ -n "$DANGER" ]; then
  echo "  中止します。次のファイルは公開してはいけません:"
  echo "$DANGER"
  echo "  .gitignore を確認してください。"
  exit 1
fi
echo "  OK: ログインセッション・収集データは除外されています"

if git diff --cached --quiet && git rev-parse HEAD >/dev/null 2>&1; then
  echo "  変更なし。コミットは省略します。"
else
  git commit -q -m "Threads伸びてる投稿コレクター"
  echo "  コミットしました。"
fi

echo "== 4. GitHub にリポジトリを作成 =="
if git remote get-url origin >/dev/null 2>&1; then
  echo "  origin は設定済み: $(git remote get-url origin)"
  git push -u origin HEAD
else
  # 公開リポジトリとして作成する。GitHub Pages の無料枠が公開限定のため。
  gh repo create "$REPO_NAME" --public --source=. --remote=origin --push
fi

echo "== 5. GitHub Pages を有効化 =="
OWNER=$(gh api user --jq .login)
gh api -X POST "repos/$OWNER/$REPO_NAME/pages" \
  -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 \
  || gh api -X PUT "repos/$OWNER/$REPO_NAME/pages" \
       -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 \
  || echo "  （既に有効か、手動設定が必要です）"

echo
echo "==================================================="
echo "公開URL: https://$OWNER.github.io/$REPO_NAME/"
echo "==================================================="
echo "反映まで初回は数分かかります。"
echo "次: bash scripts/install_launchd.sh で1日3回の自動更新を登録"
