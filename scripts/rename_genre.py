#!/usr/bin/env python3
"""
蓄積データのジャンル名を付け替える。

config/keywords.json のジャンル名を変えると、それ以降に集めた投稿だけが
新しい名前になり、蓄積済みの投稿は古い名前のまま残る。ページには新旧の
チップが両方並び、どちらを押しても半分しか出てこない状態になる。
名前を変えたら、このスクリプトで蓄積側も揃える。

  python3 scripts/rename_genre.py --dry-run 育毛 育毛・頭皮ケア   # 件数だけ確認
  python3 scripts/rename_genre.py 育毛 育毛・頭皮ケア             # 実行

書き換える前に data/posts.json.bak へ退避する。
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_FILE  # noqa: E402


def rename_in_store(store, old, new):
    """
    store のジャンル名を付け替える。副作用は store への書き込みのみ。
    返り値は (書き換えた投稿数, 統合された投稿数)。

    付け替え先がすでに付いている投稿では、同じ名前が2つ並ばないようにまとめる。
    """
    changed = 0
    merged = 0
    for post in store.get("posts", {}).values():
        genres = post.get("genres") or []
        if old not in genres:
            continue
        # 順序を保ったまま置き換え、重複を落とす
        replaced = []
        for g in genres:
            g = new if g == old else g
            if g not in replaced:
                replaced.append(g)
        if len(replaced) < len(genres):
            merged += 1
        post["genres"] = replaced
        changed += 1
    return changed, merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old", help="今のジャンル名")
    parser.add_argument("new", help="新しいジャンル名")
    parser.add_argument("--input", type=Path, default=DATA_FILE)
    parser.add_argument("--dry-run", action="store_true", help="保存せず件数だけ表示する")
    args = parser.parse_args()

    if args.old == args.new:
        raise SystemExit("同じ名前が指定されています。")
    if not args.input.exists():
        raise SystemExit(f"データがありません: {args.input}")

    store = json.loads(args.input.read_text(encoding="utf-8"))
    changed, merged = rename_in_store(store, args.old, args.new)

    print(f"「{args.old}」→「{args.new}」: {changed} 件")
    if merged:
        print(f"  うち {merged} 件は、すでに付いていた「{args.new}」とまとめました。")
    if changed == 0:
        print("  該当がないので、何もしませんでした。")
        return 0
    if args.dry_run:
        print("\n--dry-run のため保存しませんでした。")
        return 0

    backup = args.input.with_suffix(args.input.suffix + ".bak")
    shutil.copy2(args.input, backup)
    tmp = args.input.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(args.input)

    print(f"\n保存しました: {args.input}")
    print(f"元のデータ: {backup}")
    print("次: python3 scripts/build_html.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
