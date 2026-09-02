#!/usr/bin/env python3
"""
collect.py のジャンルローテーションを検証する。ブラウザも通信も使わない。

守りたいこと:
  1. 1回の実行で処理する語数が一定であること（実行時間が読めなくなるのを防ぐ）
  2. 1日3回まわせば全ジャンルが1周すること（収集されないジャンルを作らない）
  3. 設定ファイルを編集しても位置がずれず、壊れても止まらないこと
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from collect import (  # noqa: E402
    DEFAULT_BATCH,
    build_pairs,
    genres_with_data,
    select_batch,
    write_batch_config,
)
from common import CONFIG_FILE  # noqa: E402

PASS = 0
FAIL = 0


def check(label, cond, actual=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}  → 実際: {actual!r}")


def state_of(pair):
    return {"last_genre": pair[0], "last_keyword": pair[1]}


SAMPLE = {
    "genres": {
        "あ": {"keywords": ["a1", "a2", "a3"], "required_any": ["A"]},
        "い": {"keywords": ["i1", "i2"], "required_any": ["I"]},
        "う": {"keywords": ["u1", "u2"], "required_any": []},
    }
}
SAMPLE_PAIRS = [("あ", "a1"), ("あ", "a2"), ("あ", "a3"),
                ("い", "i1"), ("い", "i2"), ("う", "u1"), ("う", "u2")]

print("--- 設定の読み取り ---")
pairs = build_pairs(SAMPLE)
check("設定に書いた順序がそのまま収集順になる", pairs == SAMPLE_PAIRS, pairs)
check("旧形式（配列だけ）も読める",
      build_pairs({"genres": {"x": ["k1", "k2"]}}) == [("x", "k1"), ("x", "k2")], None)
check("空の設定でも落ちない", build_pairs({}) == [], None)

print("--- 続きから切り出す ---")
batch, start = select_batch(pairs, {}, 3)
check("状態が無ければ先頭から", batch == pairs[:3], batch)
check("開始位置は0", start == 0, start)

batch, start = select_batch(pairs, state_of(("あ", "a3")), 3)
check("前回の次から始まる", batch == [("い", "i1"), ("い", "i2"), ("う", "u1")], batch)
check("開始位置を返す", start == 3, start)

batch, start = select_batch(pairs, state_of(("う", "u1")), 3)
check("末尾をまたぐと先頭に戻る",
      batch == [("う", "u2"), ("あ", "a1"), ("あ", "a2")], batch)

batch, start = select_batch(pairs, state_of(("う", "u2")), 3)
check("最後まで行ったら先頭から", batch == pairs[:3], batch)
check("そのときの開始位置は0", start == 0, start)

print("--- 設定を編集したとき ---")
batch, start = select_batch(pairs, state_of(("消えた", "消えた語")), 3)
check("覚えていた語が消えていたら先頭から", batch == pairs[:3], batch)
batch, start = select_batch(pairs, {}, 3)
check("状態ファイルが壊れていても（空扱い）落ちない", len(batch) == 3, batch)
# ジャンルを足しても、覚えているのは位置ではなく語なので後ろにずれない
grown = pairs[:3] + [("新", "n1")] + pairs[3:]
batch, start = select_batch(grown, state_of(("あ", "a3")), 2)
check("途中にジャンルを足しても位置がずれない", batch == [("新", "n1"), ("い", "i1")], batch)

print("--- 未収集ジャンルの割り出し（--missing） ---")
store = {"posts": {
    "a": {"genres": ["あ"]},
    "b": {"genres": ["あ", "い"]},
    "c": {"genres": []},
    "d": {},
}}
have = genres_with_data(store)
check("1件でもあるジャンルを拾う", have == {"あ", "い"}, sorted(have))
check("ジャンル欄が空でも壊れない", genres_with_data({"posts": {"x": {}}}) == set(), None)
check("蓄積が空なら全ジャンルが未収集", genres_with_data({}) == set(), None)
missing_pairs = [p for p in pairs if p[0] not in have]
check("未収集ジャンルの語だけ残る", {g for g, _ in missing_pairs} == {"う"}, missing_pairs)
check("収集済みの語は入らない", all(g == "う" for g, _ in missing_pairs), missing_pairs)

print("--- 全部まわす指定 ---")
check("batch=0 なら全部", select_batch(pairs, {}, 0)[0] == pairs, None)
check("batch が語数以上なら全部", select_batch(pairs, {}, 99)[0] == pairs, None)
check("キーワードが無ければ空", select_batch([], {}, 3)[0] == [], None)

print("--- 今回の分だけの設定ファイル ---")
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "batch.json"
    genres = write_batch_config(SAMPLE, [("あ", "a2"), ("い", "i1"), ("あ", "a3")], out)
    written = json.loads(out.read_text(encoding="utf-8"))
    check("今回の語だけが入る",
          written["genres"]["あ"]["keywords"] == ["a2", "a3"], written["genres"]["あ"])
    check("またいだジャンルも入る",
          written["genres"]["い"]["keywords"] == ["i1"], written["genres"].get("い"))
    check("回さないジャンルは入らない", "う" not in written["genres"], list(written["genres"]))
    # ここが抜けると関連度フィルタが効かず、無関係な投稿が蓄積に入る
    check("required_any を元の設定から引き継ぐ",
          written["genres"]["あ"]["required_any"] == ["A"], written["genres"]["あ"])
    check("画面表示用にジャンルを返す", set(genres) == {"あ", "い"}, list(genres))

print("--- 実際の config/keywords.json ---")
config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
real = build_pairs(config)
check(f"キーワードが {len(real)} 語ある", len(real) > 0, len(real))
check("同じ (ジャンル, キーワード) が重複しない", len(set(real)) == len(real), len(real))

missing = [g for g, e in config["genres"].items() if not e.get("required_any")]
# Threadsの検索は語が緩く一致する。required_any が空だと関連度フィルタが素通りする
check("全ジャンルに required_any がある", missing == [], missing)

empty = [g for g, e in config["genres"].items() if not e.get("keywords")]
check("全ジャンルにキーワードがある", empty == [], empty)

# 1日3回の実行で全ジャンルを一周できることが、この方式の前提
covered = set()
state = {}
for _ in range(3):
    batch, _start = select_batch(real, state, DEFAULT_BATCH)
    covered.update(batch)
    state = state_of(batch[-1])
uncovered = [f"{g}/{k}" for g, k in real if (g, k) not in covered]
check(f"1日3回（{DEFAULT_BATCH}語×3）で全語をまわりきる", uncovered == [], uncovered)

# 1回あたりの語数が跳ねると、実行時間が読めなくなる
sizes = []
state = {}
for _ in range(9):
    batch, _start = select_batch(real, state, DEFAULT_BATCH)
    sizes.append(len(batch))
    state = state_of(batch[-1])
check("1回の語数は常に一定", set(sizes) == {DEFAULT_BATCH}, sizes)

print(f"\n結果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
