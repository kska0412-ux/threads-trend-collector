#!/usr/bin/env bash
# GitHub Pages（無料・公開リポジトリ）で配信するための初期設定。最初に1回だけ実行する。
#
#   bash scripts/setup_github.sh [リポジトリ名]
#
# 既定のリポジトリ名は threads-trend-collector。
# 何度実行しても壊れないように作ってある（途中で失敗したら直して再実行してよい）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REPO_NAME="${1:-threads-trend-collector}"

echo "== 1. 前提の確認 =="
command -v gh >/dev/null || { echo "  gh コマンドがありません: brew install gh"; exit 1; }
command -v git >/dev/null || { echo "  git コマンドがありません"; exit 1; }

if ! gh auth status >/dev/null 2>&1; then
  echo "  GitHub の認証が切れています。先に次を実行してください:"
  echo "    gh auth login"
  exit 1
fi

if [ ! -f docs/index.html ]; then
  echo "  docs/index.html がありません。先に次を実行してください:"
  echo "    python3 scripts/build_html.py"
  exit 1
fi

OWNER="$(gh api user --jq .login)"
echo "  OK: gh 認証済み（${OWNER}）"

echo "== 2. git リポジトリを用意 =="
if [ -d .git ]; then
  echo "  既にあります。そのまま使います。"
else
  git init -q -b main
  echo "  作成しました。"
fi

git add -A

echo "== 3. 公開してはいけないファイルが混ざっていないか確認 =="
# ここが最後の砦。.browser-profile には Threads のログインCookieが入る。
DANGER="$(git status --porcelain | grep -iE "browser-profile|Cookies|Login Data|posts\.json|raw_latest|node_modules|\.env" || true)"
if [ -n "$DANGER" ]; then
  echo "  中止します。次のファイルは公開してはいけません:"
  echo "$DANGER"
  echo "  .gitignore を確認してください。"
  exit 1
fi
echo "  OK: ログインセッション・収集データは除外されています"

if git rev-parse HEAD >/dev/null 2>&1 && git diff --cached --quiet; then
  echo "  変更なし。コミットは省略します。"
else
  git commit -q -m "Threads Research Tool"
  echo "  コミットしました。"
fi

echo "== 4. GitHub にリポジトリを用意 =="
if git remote get-url origin >/dev/null 2>&1; then
  echo "  origin は設定済み: $(git remote get-url origin)"
elif gh repo view "$OWNER/$REPO_NAME" >/dev/null 2>&1; then
  echo "  GitHub 側に既にあります。origin として紐づけます。"
  git remote add origin "https://github.com/$OWNER/$REPO_NAME.git"
else
  # GitHub Pages の無料枠は公開リポジトリのみ。
  gh repo create "$REPO_NAME" --public --description "Threads Research Tool（薄毛、育毛、フェイシャル ver）"
  git remote add origin "https://github.com/$OWNER/$REPO_NAME.git"
  echo "  作成しました。"
fi

echo "== 5. push =="
git push -u origin HEAD
echo "  完了。"

echo "== 6. GitHub Pages を有効化 =="
# ネストした JSON を送るため、-f ではなく --input で明示的に渡す。
PAGES_BODY='{"source":{"branch":"main","path":"/docs"}}'
if gh api "repos/$OWNER/$REPO_NAME/pages" >/dev/null 2>&1; then
  echo "$PAGES_BODY" | gh api -X PUT "repos/$OWNER/$REPO_NAME/pages" --input - >/dev/null \
    && echo "  設定を更新しました。" \
    || echo "  更新に失敗しました。リポジトリの Settings → Pages で /docs を指定してください。"
else
  echo "$PAGES_BODY" | gh api -X POST "repos/$OWNER/$REPO_NAME/pages" --input - >/dev/null \
    && echo "  有効にしました。" \
    || echo "  有効化に失敗しました。リポジトリの Settings → Pages で main / docs を指定してください。"
fi

URL="$(gh api "repos/$OWNER/$REPO_NAME/pages" --jq .html_url 2>/dev/null || true)"
[ -z "$URL" ] && URL="https://$OWNER.github.io/$REPO_NAME/"

echo
echo "==================================================="
echo "公開URL: $URL"
echo "==================================================="
echo "初回は反映まで数分かかります。"
echo
echo "次: bash scripts/install_launchd.sh"
echo "    朝7時 / 昼13時 / 夜21時 に自動で更新されるようになります。"
