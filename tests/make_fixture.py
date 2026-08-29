#!/usr/bin/env python3
"""
HTML の動作確認用テストデータを生成する。API を叩かずに build_html.py を検証するため。

いいね数と経過時間の組み合わせを意図的にばらけさせてある:
  - 古くていいねが多い投稿  → いいね順で上位、伸び順では沈む
  - 新しくていいねが中程度  → 伸び順で上位
  - timestamp 欠損の投稿    → 落ちずに最後尾へ回るか
  - HTML特殊文字を含む投稿  → エスケープされるか

使い方:
  python3 tests/make_fixture.py --output /tmp/fixture_posts.json
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))

# (id, username, text, 経過時間, likes, genres, keywords)
SAMPLES = [
    ("p1", "hair_clinic_jp",
     "生え際が後退してきたら、まず疑うべきは血流です。\n\nシャンプーを変える前に、頭皮が動くか確認してください。\n指で押して動かない人は要注意。",
     4, 1250, ["薄毛"], ["生え際 後退", "AGA"]),
    ("p2", "esthe_mika",
     "小顔になりたい人へ。\n\nマッサージより先に、噛みしめを直してください。\n\n夜、歯が触れてる時間が長い人ほどエラが張ります。",
     30, 3400, ["フェイシャル"], ["小顔", "たるみ 改善"]),
    ("p3", "ikumou_lab",
     "育毛剤って、実は「つける量」より「つける場所」。\n\n毛先じゃなく頭皮。\n当たり前だけど8割の人が間違えてます。",
     2, 85, ["育毛"], ["育毛剤", "頭皮ケア"]),
    ("p4", "skin_pro_88",
     "毛穴の黒ずみ、ゴシゴシ洗うと悪化します。\n\n黒ずみの正体は皮脂の酸化。\n落とすんじゃなくて、酸化させない。",
     200, 8900, ["フェイシャル"], ["毛穴 ケア"]),
    ("p5", "kamiwaza_dr",
     "抜け毛が増える季節、実は秋です。\n\n夏の紫外線ダメージが3ヶ月遅れで出る。\n今抜けてるのは、7月のあなたのせい。",
     12, 620, ["薄毛", "育毛"], ["抜け毛 対策", "発毛"]),
    ("p6", "test_edge",
     'タイムスタンプ欠損のテスト投稿 <script>alert(1)</script> & "引用" も含む',
     None, 42, ["育毛"], ["頭皮マッサージ"]),
    ("p7", "face_yoga_ne",
     "ほうれい線は「口輪筋」じゃなくて「頬の位置」。\n\n下がった頬が折れてできる線なので、口周りを鍛えても消えません。",
     1, 15, ["フェイシャル"], ["ほうれい線", "リフトアップ"]),
    ("p8", "aga_memo",
     "AGA治療、月1万円が高いと思うなら植毛の見積もり取ってみてください。\n\n桁が変わります。",
     700, 2100, ["薄毛"], ["AGA"]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    now = datetime.now(JST)
    posts = {}
    for pid, user, text, hours_ago, likes, genres, keywords in SAMPLES:
        if hours_ago is None:
            ts = None
        else:
            ts = (now - timedelta(hours=hours_ago)).astimezone(
                timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S+0000")
        posts[pid] = {
            "id": pid,
            "username": user,
            "text": text,
            "timestamp": ts,
            "permalink": f"https://www.threads.net/@{user}/post/{pid}",
            "like_count": likes,
            "genres": genres,
            "keywords": keywords,
            "first_seen": now.isoformat(),
            "last_updated": now.isoformat(),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"posts": posts, "updated_at": now.isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"テストデータを生成: {args.output}（{len(posts)} 件）")


if __name__ == "__main__":
    main()
