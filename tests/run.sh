#!/usr/bin/env bash
# 回帰テスト。ブラウザも通信も使わないので、いつでも再現する。
#
#   bash tests/run.sh
#
# 検証するもの:
#   1. extract.mjs   Threads の JSON から投稿を抜き出すロジック
#   1b. retry.mjs    取得失敗・件数不足のやり直し判定
#   2. build_html.py 生成した HTML を jsdom で組み立てて並び替え・絞り込みを確認
#   3. collect.py    取得済みデータのマージ（重複排除・いいね更新）
#   3b. collect.py   ジャンルのローテーション（1日3回で全ジャンルを一周するか）
#   4. publish.sh    GitHub Pages への公開判定（ローカルのベアリポジトリで検証）
#   5. run_collect.sh 自動実行の排他ロックと、失敗時の掛け直し
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/threads-trend-collector-test"
mkdir -p "$WORK"

if [ ! -d "$WORK/node_modules/jsdom" ]; then
  echo "jsdom を取得します（初回のみ）..."
  npm install --prefix "$WORK" --cache "$WORK/.npm-cache" jsdom --no-audit --no-fund
fi

echo "===== 1. 投稿抽出ロジック ====="
node "$ROOT/tests/verify_extract.mjs"

echo
echo "===== 2. やり直し判定 ====="
node "$ROOT/tests/verify_retry.mjs"

echo
echo "===== 3. マージ処理 ====="
python3 "$ROOT/tests/verify_merge.py"

echo
echo "===== 4. 収集のローテーション ====="
python3 "$ROOT/tests/verify_rotation.py"

echo
echo "===== 5. 表示範囲の絞り込み ====="
python3 "$ROOT/tests/verify_select.py"

echo
echo "===== 6. HTML生成 ====="
python3 "$ROOT/tests/make_fixture.py" --output "$WORK/fixture_posts.json"
python3 "$ROOT/scripts/build_html.py" --input "$WORK/fixture_posts.json" --output "$WORK/preview.html"
# 件数上限に当たったときの表示も確かめるため、絞り込みが起きる版も作る
python3 "$ROOT/scripts/build_html.py" --input "$WORK/fixture_posts.json" --output "$WORK/preview_trimmed.html" --max-posts 3 > /dev/null
SCRATCH="$WORK" node "$ROOT/tests/verify_html.mjs"

echo
echo "===== 7. 改行の作法 ====="
SCRATCH="$WORK" node "$ROOT/tests/verify_wrapping.mjs"

echo
echo "===== 8. 公開判定 ====="
bash "$ROOT/tests/verify_publish.sh"

echo
echo "===== 9. 公開の安全性 ====="
bash "$ROOT/tests/verify_safety.sh"

echo
echo "===== 10. 自動実行の排他と再試行 ====="
bash "$ROOT/tests/verify_lock.sh"

echo
echo "全テスト通過"
