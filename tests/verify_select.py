#!/usr/bin/env python3
"""build_html.py の表示範囲の絞り込みを検証する。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from build_html import select_rows  # noqa: E402

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


def row(rid, likes, velocity, age_hours):
    return {"id": rid, "likes": likes, "velocity": velocity, "ageHours": age_hours}


print("--- 期間での絞り込み ---")
rows = [row("new", 10, 1, 24), row("mid", 10, 1, 24 * 100), row("old", 10, 1, 24 * 200)]
kept, aged, over = select_rows(rows, 180, 0)
check("180日以内の2件が残る", {r["id"] for r in kept} == {"new", "mid"}, [r["id"] for r in kept])
check("期間外の件数を返す", aged == 1, aged)
check("上限による除外は0", over == 0, over)

kept, aged, over = select_rows(rows, 0, 0)
check("0日指定で期間無制限", len(kept) == 3, len(kept))

rows_no_ts = [row("a", 10, 1, None), row("b", 10, 1, 24 * 500)]
kept, aged, over = select_rows(rows_no_ts, 180, 0)
check("投稿日時が不明なものは残す", {r["id"] for r in kept} == {"a"}, [r["id"] for r in kept])

print("--- 件数上限 ---")
many = [row(f"p{i}", i, i, 24) for i in range(100)]
kept, aged, over = select_rows(many, 180, 0)
check("上限0なら全件", len(kept) == 100, len(kept))
kept, aged, over = select_rows(many, 180, 200)
check("上限が件数より大きければ全件", len(kept) == 100, len(kept))
check("その場合の超過は0", over == 0, over)
kept, aged, over = select_rows(many, 180, 10)
check("上限ちょうどまで絞る", len(kept) == 10, len(kept))
check("超過件数を返す", over == 90, over)
check("同じ投稿が重複しない", len({r["id"] for r in kept}) == len(kept), len(kept))

print("--- 急上昇中の投稿を切り捨てないこと（この方式の要） ---")
# いいねは多いが古くて伸びていない投稿を大量に用意する
veterans = [row(f"v{i}", 10000 + i, 0.5, 24 * 150) for i in range(50)]
# いいねは少ないが今まさに伸びている投稿
rising = row("rising", 300, 999.0, 3)
kept, aged, over = select_rows(veterans + [rising], 180, 10)
ids = {r["id"] for r in kept}
check("急上昇中の投稿が残る", "rising" in ids, sorted(ids))
check("いいね最多の投稿も残る", "v49" in ids, sorted(ids))
check("上限は守られる", len(kept) == 10, len(kept))

print("--- いいね順だけで切った場合との比較 ---")
by_likes_only = sorted(veterans + [rising], key=lambda r: -r["likes"])[:10]
check("いいね順だけだと急上昇が落ちる（採用しなかった方式）",
      "rising" not in {r["id"] for r in by_likes_only}, None)

print("--- ジャンルごとの枠取り ---")


def grow(rid, likes, velocity, genres):
    r = row(rid, likes, velocity, 24)
    r["genres"] = genres
    return r


# いいねの桁が違う2ジャンル。枠取りが無いと大きいほうが上限を食い切る
big = [grow(f"big{i}", 10000 + i, 100.0, ["ダイエット"]) for i in range(50)]
niche = [grow(f"nic{i}", 10 + i, 0.1, ["エステ・リラクゼーション"]) for i in range(50)]

kept, aged, over = select_rows(big + niche, 180, 20, per_genre=0)
seen = {g for r in kept for g in r["genres"]}
check("枠取りなしだとニッチなジャンルが丸ごと消える（採用しなかった方式）",
      "エステ・リラクゼーション" not in seen, sorted(seen))

kept, aged, over = select_rows(big + niche, 180, 20, per_genre=8)
counts = {}
for r in kept:
    for g in r["genres"]:
        counts[g] = counts.get(g, 0) + 1
check("枠取りありなら両ジャンルが残る", set(counts) == {"ダイエット", "エステ・リラクゼーション"}, counts)
check("ニッチなジャンルが枠の数だけ残る", counts.get("エステ・リラクゼーション", 0) >= 8, counts)
check("いいねの大きいジャンルは残りの枠も取る", counts.get("ダイエット", 0) > 8, counts)
check("上限は守られる", len(kept) == 20, len(kept))
check("同じ投稿が重複しない", len({r["id"] for r in kept}) == len(kept), len(kept))

# 枠の合計が上限を超えるときは、ジャンルの並び順で後ろが切り捨てられてはいけない
crowded = [grow(f"g{gi}p{i}", 100 - i, 1.0, [f"ジャンル{gi}"])
           for gi in range(10) for i in range(20)]
kept, aged, over = select_rows(crowded, 180, 15, per_genre=80)
check("枠の合計が上限を超えるときは均等に縮む", len(kept) == 15, len(kept))
check("縮んでも全ジャンルが1件以上残る",
      len({g for r in kept for g in r["genres"]}) == 10,
      sorted({g for r in kept for g in r["genres"]}))

# 1つの投稿が複数ジャンルに属していても、枠を二重に使わない
shared = [grow(f"sh{i}", 100 - i, 1.0, ["A", "B"]) for i in range(30)]
kept, aged, over = select_rows(shared, 180, 10, per_genre=5)
check("掛け持ち投稿でも上限を超えない", len(kept) == 10, len(kept))

# ジャンルが付いていない蓄積データ（旧形式）でも落ちない
kept, aged, over = select_rows([row(f"p{i}", i, i, 24) for i in range(50)], 180, 10)
check("ジャンル無しのデータでも上限どおり", len(kept) == 10, len(kept))

print("--- 期間と件数の併用 ---")
mixed = [row(f"n{i}", i, i, 24) for i in range(20)] + [row(f"o{i}", 999, 999, 24 * 400) for i in range(20)]
kept, aged, over = select_rows(mixed, 180, 5)
check("古いものは件数上限の前に除外される",
      all(r["id"].startswith("n") for r in kept), [r["id"] for r in kept])
check("期間外の件数が正しい", aged == 20, aged)
check("上限超過の件数が正しい", over == 15, over)

print(f"\n結果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
