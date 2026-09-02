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
    MAX_BATCH,
    RUNS_PER_DAY,
    auto_batch,
    build_pairs,
    build_modifiers,
    failed_pairs,
    genres_with_data,
    plan_batch,
    seen_from_store,
    select_batch,
    stale_genres,
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

print("--- 設定に足したばかりの語を先に回す ---")
# 記録が無い＝初回。ここで空集合を返すと50語全部が「新しい語」になり、
# 1回で全部回そうとして数時間かかってしまう
batch, window, start = plan_batch(pairs, {}, 3, None)
check("初回は先回りしない（ローテーションどおり）", batch == pairs[:3], batch)
check("初回でも位置は進む", window == pairs[:3], window)

# 「い」のジャンルを丸ごと足した直後を想定する
seen_all = set(pairs)
seen_old = seen_all - {("い", "i1"), ("い", "i2")}
batch, window, start = plan_batch(pairs, state_of(("あ", "a1")), 3, seen_old)
check("新しい語が先頭に来る", batch[:2] == [("い", "i1"), ("い", "i2")], batch)
check("1回の語数は変わらない", len(batch) == 3, batch)
check("ローテーション側は削られた分だけ", window == [("あ", "a2")], window)
check("位置はローテーション側で進む", start == 1, start)

# 新しい語が枠を超えるとき
seen_few = {("あ", "a1")}
batch, window, start = plan_batch(pairs, {}, 2, seen_few)
check("枠を超える新しい語は次回に回す", len(batch) == 2, batch)
check("その回は位置を進めない", window == [], window)
check("進めないことが分かる形で返る", start is None, start)

# 新しい語がローテーションの窓と重なったとき、同じ語を2回引かない
seen_dup = seen_all - {("あ", "a2")}
batch, window, start = plan_batch(pairs, state_of(("あ", "a1")), 3, seen_dup)
check("重複して回さない", len(batch) == len(set(batch)), batch)
check("重なった語も済んだ扱いで位置が進む",
      ("あ", "a2") in window, window)

check("変化が無ければローテーションのまま",
      plan_batch(pairs, {}, 3, seen_all)[0] == pairs[:3], None)
check("キーワードが無ければ空", plan_batch([], {}, 3, set())[0] == [], None)

print("--- 記録ファイルが無いときの割り出し ---")
# 記録を作る前に足し引きした語を、先回りの対象から漏らさないための道
store3 = {"posts": {
    "p1": {"keywords": ["a1", "a2"]},
    "p2": {"keywords": ["i1"]},
    "p3": {},
}}
derived = seen_from_store(store3, pairs)
check("蓄積に出てくる語は済み扱い",
      derived == {("あ", "a1"), ("あ", "a2"), ("い", "i1")}, sorted(derived))
check("一度も取れていない語は新しい語のまま",
      ("う", "u1") not in derived, sorted(derived))
check("蓄積が空なら全部が新しい語", seen_from_store({}, pairs) == set(), None)
# 割り出した結果をそのまま先回りに渡せること
batch, window, start = plan_batch(pairs, {}, 3, derived)
check("割り出した結果で先回りが効く",
      batch[0] in [("あ", "a3"), ("い", "i2"), ("う", "u1"), ("う", "u2")], batch)

print("--- 設定に無いジャンルが蓄積に残っているとき ---")
store2 = {"posts": {
    "a": {"genres": ["あ"]},
    "b": {"genres": ["旧ジャンル"]},
    "c": {"genres": ["旧ジャンル", "い"]},
}}
stale = stale_genres(store2, ["あ", "い", "う"])
check("設定に無い名前だけ拾う", set(stale) == {"旧ジャンル"}, stale)
check("件数を数える", stale["旧ジャンル"] == 2, stale)
check("ズレが無ければ空", stale_genres(store2, ["あ", "い", "旧ジャンル"]) == {}, None)
# 設定が読めないときに全ジャンルを「知らない名前」と言い出すと警告が壊れる
check("設定が空なら何も言わない", stale_genres(store2, []) == {}, None)

print("--- 全部まわす指定 ---")
check("batch=0 なら全部", select_batch(pairs, {}, 0)[0] == pairs, None)
check("batch=0 は先回りの有無によらず全部",
      plan_batch(pairs, {}, 0, set())[0] == pairs, None)
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

print("--- 失敗した語は「回した語」に数えない ---")
# 回線が切れて後半が全滅した回でも、次の実行で真っ先に掛け直せるようにする
raw = {"results": [
    {"genre": "あ", "keyword": "a1", "posts": [{"id": "1"}], "error": None},
    {"genre": "あ", "keyword": "a2", "posts": [], "error": "net::ERR_INTERNET_DISCONNECTED"},
    {"genre": "い", "keyword": "i1", "posts": [], "error": "Timeout"},
    {"genre": "い", "keyword": "i2", "posts": [], "error": None},
]}
bad = failed_pairs(raw)
check("失敗した語だけ拾う", bad == {("あ", "a2"), ("い", "i1")}, sorted(bad))
check("0件でもエラーが無ければ成功扱い", ("い", "i2") not in bad, sorted(bad))
check("結果が空でも落ちない", failed_pairs({}) == set(), None)
done = [p for p in SAMPLE_PAIRS if p not in bad]
check("成功した語だけが記録に回る",
      ("あ", "a2") not in done and ("い", "i1") not in done, done)
check("失敗しなかった語は記録に残る", ("あ", "a1") in done, done)

print("--- 1回で回す語数の自動決定 ---")
# 固定値にすると、ジャンルを減らしたとき1回で全部回ってしまい（負荷が偏る）、
# 増やしたときは一周に何日もかかるのに気づけない
check("語数が無ければ0", auto_batch(0) == 0, auto_batch(0))
check("1語でも1語は回す", auto_batch(1) == 1, auto_batch(1))
check("19語なら7語（1日で一周）", auto_batch(19) == 7, auto_batch(19))
check("50語なら17語（1日で一周）", auto_batch(50) == 17, auto_batch(50))
check("1回が長くなりすぎないよう上限がある",
      auto_batch(1000) == MAX_BATCH, auto_batch(1000))
# 上限に当たらない範囲では、必ず1日で一周しきること
short = [n for n in range(1, MAX_BATCH * RUNS_PER_DAY + 1)
         if auto_batch(n) * RUNS_PER_DAY < n]
check("上限内なら1日で一周しきる", short == [], short)
check("上限を超えても語数を超える指定はしない",
      all(auto_batch(n) <= max(1, n) for n in range(1, 200)), None)

print("--- 掛け合わせ語の展開 ---")
# 「経営」を単独で検索すると飲食や一般ビジネスを拾う（実測で74%がフィルタ落ち）。
# 単独では検索せず、必ず主ジャンルと組ませる
COMBO = {
    "genres": {
        "あ": {"keywords": ["あ"], "required_any": ["A"]},
        "い": {"keywords": ["い"], "required_any": ["I"]},
    },
    "modifiers": {
        "経営": {"combine_with": ["あ", "い"], "match_any": ["経営", "売上"]},
        "手技": {"combine_with": ["い"], "match_any": ["手技"]},
        "誤り": {"combine_with": ["存在しない"], "match_any": ["x"]},
    },
}
combo_pairs = build_pairs(COMBO)
check("主ジャンルが先に来る", combo_pairs[:2] == [("あ", "あ"), ("い", "い")], combo_pairs[:2])
check("組み合わせ語ができる",
      ("あ", "あ 経営") in combo_pairs and ("い", "い 手技") in combo_pairs, combo_pairs)
# 単独の「経営」を作ってしまうと、元のノイズ問題に戻る
check("掛け合わせ語を単独では検索しない",
      not any(k in ("経営", "手技") for _, k in combo_pairs), combo_pairs)
check("組み合わせは主ジャンルに属する",
      all(g in COMBO["genres"] for g, _ in combo_pairs), combo_pairs)
check("設定に無いジャンルとは組まない",
      not any("誤り" in k for _, k in combo_pairs), combo_pairs)
check("重複しない", len(set(combo_pairs)) == len(combo_pairs), combo_pairs)
check("modifiers が無くても動く",
      build_pairs({"genres": {"x": {"keywords": ["x"]}}}) == [("x", "x")], None)

mods = build_modifiers(COMBO)
check("判定語を読める", mods["経営"] == ["経営", "売上"], mods)
check("modifiers が無ければ空", build_modifiers({"genres": {}}) == {}, None)

print("--- 実際の config/keywords.json ---")
config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
real = build_pairs(config)
check(f"キーワードが {len(real)} 語ある", len(real) > 0, len(real))
check("同じ (ジャンル, キーワード) が重複しない", len(set(real)) == len(real), len(real))

# 掛け合わせ語が単独ジャンルに残っていると、元のノイズ問題に戻る
overlap = sorted(set(config["genres"]) & set(config.get("modifiers") or {}))
check("掛け合わせ語が単独ジャンルに残っていない", overlap == [], overlap)
# 判定語が無いと、ページの2段目で絞り込めない
no_match = [m for m, e in (config.get("modifiers") or {}).items() if not e.get("match_any")]
check("全掛け合わせ語に判定語がある", no_match == [], no_match)
no_combine = [m for m, e in (config.get("modifiers") or {}).items() if not e.get("combine_with")]
check("全掛け合わせ語に相手のジャンルがある", no_combine == [], no_combine)

missing = [g for g, e in config["genres"].items() if not e.get("required_any")]
# Threadsの検索は語が緩く一致する。required_any が空だと関連度フィルタが素通りする
check("全ジャンルに required_any がある", missing == [], missing)

empty = [g for g, e in config["genres"].items() if not e.get("keywords")]
check("全ジャンルにキーワードがある", empty == [], empty)

# 1日3回の実行で全ジャンルを一周できることが、この方式の前提
real_batch = auto_batch(len(real))
covered = set()
state = {}
for _ in range(RUNS_PER_DAY):
    batch, _start = select_batch(real, state, real_batch)
    covered.update(batch)
    state = state_of(batch[-1])
uncovered = [f"{g}/{k}" for g, k in real if (g, k) not in covered]
check(f"1日{RUNS_PER_DAY}回（{real_batch}語×{RUNS_PER_DAY}）で全語をまわりきる",
      uncovered == [], uncovered)

# 1回あたりの語数が跳ねると、実行時間が読めなくなる
sizes = []
state = {}
for _ in range(9):
    batch, _start = select_batch(real, state, real_batch)
    sizes.append(len(batch))
    state = state_of(batch[-1])
check("1回の語数は常に一定", set(sizes) == {real_batch}, sizes)
# 1語あたり最悪3分。1回が1時間を超えると、途中でスリープに入る危険が上がる
check(f"最悪の実行時間が1時間以内（{real_batch}語×3分）", real_batch * 3 <= 60,
      f"{real_batch * 3}分")

print(f"\n結果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
