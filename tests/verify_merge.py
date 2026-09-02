#!/usr/bin/env python3
"""collect.py のマージ処理を検証する。ブラウザも通信も使わない。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from collect import merge_posts, is_relevant, load_required_any  # noqa: E402

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


def post(pid, likes, user="u1", text="本文"):
    return {
        "id": pid, "username": user, "text": text,
        "timestamp": "2026-08-28T10:00:00+0000",
        "permalink": f"https://www.threads.com/@{user}/post/{pid}",
        "like_count": likes,
    }


store = {"posts": {}}

print("--- 新規追加 ---")
r = merge_posts(store, [post("A", 120), post("B", 340)], "フェイシャル", "小顔", "T1")
check("新規2件・更新0件", r == (2, 0), r)
check("蓄積2件", len(store["posts"]) == 2, len(store["posts"]))

print("--- 同じ投稿が別キーワードで再ヒット ---")
r = merge_posts(store, [post("A", 155), post("C", 50)], "フェイシャル", "たるみ 改善", "T2")
check("新規1件・更新1件", r == (1, 1), r)
check("重複排除されて3件", len(store["posts"]) == 3, len(store["posts"]))
a = store["posts"]["A"]
check("いいね数が最新値に更新される", a["like_count"] == 155, a["like_count"])
check("キーワードが積み上がる", a["keywords"] == ["小顔", "たるみ 改善"], a["keywords"])

print("--- 別ジャンルで再ヒット ---")
merge_posts(store, [post("A", 155)], "薄毛", "頭皮ケア", "T3")
check("ジャンルが積み上がる", a["genres"] == ["フェイシャル", "薄毛"], a["genres"])
check("first_seen は最初のまま", a["first_seen"] == "T1", a["first_seen"])
check("last_updated は最新", a["last_updated"] == "T3", a["last_updated"])

print("--- 同じキーワードで再収集しても重複しない ---")
before_len = len(a["keywords"])
merge_posts(store, [post("A", 160)], "フェイシャル", "小顔", "T4")
check("キーワード数が増えない", len(a["keywords"]) == before_len, a["keywords"])
check("小顔が1回しか入っていない", a["keywords"].count("小顔") == 1, a["keywords"])
check("フェイシャルが1回しか入っていない", a["genres"].count("フェイシャル") == 1, a["genres"])

print("--- 壊れたデータへの耐性 ---")
r = merge_posts(store, [{"text": "idが無い"}, post("D", 10)], "育毛", "発毛", "T5")
check("id欠損はスキップして続行", r == (1, 0), r)
merge_posts(store, [{"id": "E", "username": "u", "text": "いいね数なし"}], "育毛", "発毛", "T6")
check("like_count欠損でも落ちない", store["posts"]["E"]["like_count"] is None, store["posts"]["E"]["like_count"])

print("--- いいね数が None で来ても既存値を壊さない ---")
merge_posts(store, [{"id": "A", "like_count": None}], "フェイシャル", "小顔", "T7")
check("既存のいいね数が保持される", a["like_count"] == 160, a["like_count"])

print("--- 関連度フィルタ ---")
HAIR = ["髪", "毛", "薄毛", "頭皮", "つむじ", "AGA"]
check("必須語を含めば通る", is_relevant("つむじが薄くなってきた", HAIR), None)
check("実データ例: ADHDの投稿は落ちる",
      not is_relevant("ADHDの女性へ。誰とでもすぐ打ち解けられるのに", HAIR), None)
check("実データ例: 妊娠検査薬の『薄い』は落ちる",
      not is_relevant("排卵日 ＋14日目 薄いけど確実に濃くなってる", HAIR), None)
check("実データ例: 二重の投稿は落ちる",
      not is_relevant("我が子は一重でも二重でも特段に可愛い", HAIR), None)
check("実データ例: 薄毛の悩みは通る",
      is_relevant("33歳でこの薄さ…薄毛治療しないと", HAIR), None)
check("実データ例: 地肌の話も通る（『毛』を含む）",
      is_relevant("髪の毛以外につむじある人に聞いてみたい", HAIR), None)
check("必須語が空ならフィルタしない", is_relevant("全く無関係な文章", []), None)
check("本文がNoneでも落ちない", is_relevant(None, HAIR) is False, None)
check("本文が空文字でも落ちない", is_relevant("", HAIR) is False, None)

print("--- 設定の読み込み ---")
table = load_required_any()
# ジャンルは config/keywords.json で足し引きするので、数ではなく中身で確かめる
check("設定にあるジャンルを全部読める", len(table) >= 3, list(table))
check("薄毛の必須語が入っている", "つむじ" in table["薄毛"], table["薄毛"][:5])
check("毛穴・ニキビの必須語が入っている",
      "毛穴" in table["毛穴・ニキビ"], table["毛穴・ニキビ"][:5])
check("全ジャンルに必須語がある",
      all(v for v in table.values()), [g for g, v in table.items() if not v])

print(f"\n結果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
