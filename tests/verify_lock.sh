#!/usr/bin/env bash
# run_collect.sh の排他ロックと再試行を検証する。
# 本物のブラウザもgitも使わず、collect.py などを差し替えた偽の作業場で動かす。
#
# 守りたいこと:
#   1. 実行が重なったら後発は静かに譲る（3分待って失敗する今の挙動をなくす）
#   2. 前回が異常終了して残ったロックで、二度と動かなくならない
#   3. 一時的な失敗は、次のスロット（最大8時間後）を待たずに掛け直す
#   4. 掛け直しても駄目なら、ページは更新しないで終わる
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0; FAIL=0

check() {
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "  OK   $1";
  else FAIL=$((FAIL+1)); echo "  FAIL $1  → 期待 $3 / 実際 $2"; fi
}

contains() {
  if grep -q "$2" "$1" 2>/dev/null; then echo "yes"; else echo "no"; fi
}

# 偽の作業場を作る。collect.py は「指定回数だけ失敗してから成功する」偽物に差し替える。
setup() {
  W="${TMPDIR:-/tmp}/ttc-lock-test-$$-$RANDOM"
  mkdir -p "$W/scripts" "$W/logs"
  cp "$ROOT/scripts/run_collect.sh" "$W/scripts/"

  # 失敗させたい回数を FAIL_TIMES に書いておく。呼ばれるたびに attempts が増える。
  cat > "$W/scripts/collect.py" <<'PY'
import pathlib, sys
here = pathlib.Path(__file__).resolve().parent.parent
count = here / "attempts"
n = int(count.read_text()) + 1 if count.exists() else 1
count.write_text(str(n))
fail_times = int((here / "FAIL_TIMES").read_text()) if (here / "FAIL_TIMES").exists() else 0
print(f"収集の呼び出し {n} 回目")
sys.exit(1 if n <= fail_times else 0)
PY

  cat > "$W/scripts/build_html.py" <<'PY'
import pathlib
pathlib.Path(__file__).resolve().parent.parent.joinpath("built").write_text("1")
print("HTMLを作りました")
PY

  cat > "$W/scripts/publish.sh" <<'SH'
echo "published" > "$(dirname "$0")/../published"
exit 0
SH
}

teardown() { rm -rf "$W"; }

# caffeinate での再実行は本筋ではないので飛ばす。待ち時間も1秒に縮める。
run_it() { ( cd "$W" && TTC_AWAKE=1 TTC_RETRY_WAITS="1 1" bash scripts/run_collect.sh >/dev/null 2>&1 ); echo $?; }

echo "--- 1. 正常時 ---"
setup
echo 0 > "$W/FAIL_TIMES"
STATUS="$(run_it)"
check "終了コード0" "$STATUS" "0"
check "収集を1回だけ呼ぶ" "$(cat "$W/attempts")" "1"
check "HTMLを作る" "$([ -f "$W/built" ] && echo yes || echo no)" "yes"
check "公開まで進む" "$([ -f "$W/published" ] && echo yes || echo no)" "yes"
check "完了ログが出る" "$(contains "$W/logs/collect.log" "===== 完了 =====")" "yes"
check "終わったらロックが残らない" "$([ -d "$W/logs/collect.lock" ] && echo yes || echo no)" "no"
teardown

echo
echo "--- 2. 一時的に失敗しても掛け直す ---"
setup
echo 2 > "$W/FAIL_TIMES"
STATUS="$(run_it)"
check "終了コード0" "$STATUS" "0"
check "3回呼んで成功する" "$(cat "$W/attempts")" "3"
check "掛け直したことがログに残る" "$(contains "$W/logs/collect.log" "秒後に掛け直します")" "yes"
check "何回目で成功したか残る" "$(contains "$W/logs/collect.log" "3 回目で収集に成功")" "yes"
check "公開まで進む" "$([ -f "$W/published" ] && echo yes || echo no)" "yes"
teardown

echo
echo "--- 3. 掛け直しても駄目なとき ---"
setup
echo 99 > "$W/FAIL_TIMES"
STATUS="$(run_it)"
check "終了コード1" "$STATUS" "1"
check "3回で見切りをつける" "$(cat "$W/attempts")" "3"
# ここでページを更新すると、古い内容のまま「更新した」ように見えてしまう
check "HTMLは作らない" "$([ -f "$W/built" ] && echo yes || echo no)" "no"
check "公開もしない" "$([ -f "$W/published" ] && echo yes || echo no)" "no"
check "失敗がログに残る" "$(contains "$W/logs/collect.log" "3 回失敗")" "yes"
check "失敗してもロックは残らない" "$([ -d "$W/logs/collect.lock" ] && echo yes || echo no)" "no"
teardown

echo
echo "--- 4. 実行が重なったとき ---"
setup
echo 0 > "$W/FAIL_TIMES"
# 生きているプロセスがロックを持っている状態を作る
sleep 30 &
HOLDER=$!
mkdir -p "$W/logs/collect.lock"
echo "$HOLDER" > "$W/logs/collect.lock/pid"
STATUS="$(run_it)"
check "終了コード0（失敗扱いにしない）" "$STATUS" "0"
check "収集を呼ばない" "$([ -f "$W/attempts" ] && echo yes || echo no)" "no"
check "譲ったことがログに残る" "$(contains "$W/logs/collect.log" "先行する収集が実行中")" "yes"
check "先行のロックを壊さない" "$(cat "$W/logs/collect.lock/pid")" "$HOLDER"
kill "$HOLDER" 2>/dev/null
wait "$HOLDER" 2>/dev/null
teardown

echo
echo "--- 5. 前回が異常終了して残ったロック ---"
setup
echo 0 > "$W/FAIL_TIMES"
# 存在しないPIDを書いておく。放置すると二度と動かなくなる状況
mkdir -p "$W/logs/collect.lock"
echo "999999" > "$W/logs/collect.lock/pid"
STATUS="$(run_it)"
check "終了コード0" "$STATUS" "0"
check "片付けて実行する" "$(cat "$W/attempts")" "1"
check "片付けたことがログに残る" "$(contains "$W/logs/collect.log" "異常終了した跡")" "yes"
check "終わったらロックが残らない" "$([ -d "$W/logs/collect.lock" ] && echo yes || echo no)" "no"
teardown

echo
echo "--- 6. PIDファイルごと壊れたロック ---"
setup
echo 0 > "$W/FAIL_TIMES"
mkdir -p "$W/logs/collect.lock"   # pid ファイル無し
STATUS="$(run_it)"
check "終了コード0" "$STATUS" "0"
check "片付けて実行する" "$(cat "$W/attempts")" "1"
teardown

echo
echo "--- 7. 日本語メッセージの中の変数 ---"
# bash は $OTHER）のような書き方で、全角括弧まで変数名として読む。
# set -u と組み合わさると unbound variable で落ちる（実際に踏んだ）
BAD="$(grep -lP '\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]' "$ROOT"/scripts/*.sh "$ROOT"/tests/*.sh 2>/dev/null | tr '\n' ' ')"
check "変数の直後に非ASCIIを置いていない（波括弧で囲んでいる）" "${BAD:-none}" "none"
for f in "$ROOT"/scripts/*.sh "$ROOT"/tests/*.sh; do
  check "構文が通る: $(basename "$f")" "$(bash -n "$f" 2>&1 >/dev/null && echo ok || echo ng)" "ok"
done

echo
echo "結果: $PASS pass / $FAIL fail"
[ "$FAIL" -eq 0 ]
