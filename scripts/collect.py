#!/usr/bin/env python3
"""
Threads から投稿を集めて data/posts.json に蓄積する。

実際にブラウザを動かすのは scripts/scrape.mjs（Playwright）。
このスクリプトはそれを呼び出して、結果を蓄積データにマージする役目を持つ。

蓄積の方針:
  - 投稿ID をキーに重複排除する
  - 再収集時は like_count を最新値で上書きする（投稿は時間とともに伸びるため）
  - 同じ投稿が複数キーワードでヒットしたら、キーワードとジャンルを積み上げる

初回だけログインが要る:
  python3 scripts/collect.py --login

ジャンルが増えても1回の実行時間を一定に保つため、既定ではローテーションする:
  全キーワードを config/keywords.json の順に一列に並べ、前回の続きから
  --batch 語だけ処理する。1日3回の実行で全ジャンルを一周する。
  進み具合は data/rotation.json に残る。

収集:
  python3 scripts/collect.py                       # 続きから17語
  python3 scripts/collect.py --missing             # まだ0件のジャンルだけ埋める
  python3 scripts/collect.py --all                 # 全ジャンル（数時間かかる）
  python3 scripts/collect.py --genre 脱毛          # 1ジャンルだけ今すぐ
  python3 scripts/collect.py --limit 3 --headful   # 試運転（3キーワードだけ画面を見ながら）
  python3 scripts/collect.py --dry-run             # 保存せず件数だけ確認
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import BASE_DIR, CONFIG_FILE, DATA_FILE, now_jst_iso  # noqa: E402

SCRAPER = BASE_DIR / "scripts" / "scrape.mjs"
RAW_FILE = BASE_DIR / "data" / "raw_latest.json"

# ローテーションの進み具合と、今回の分だけを書き出した設定ファイル。
# どちらも data/ 配下なので .gitignore に入っていて、公開リポジトリには出ない。
ROTATION_FILE = BASE_DIR / "data" / "rotation.json"
BATCH_FILE = BASE_DIR / "data" / "_batch_keywords.json"
# 一度でも収集にかけたキーワードの記録。設定に足したばかりの語を見分けるために使う。
SEEN_FILE = BASE_DIR / "data" / "keywords_seen.json"

# 1日に走る回数（launchd の設定と合わせてある）。
RUNS_PER_DAY = 3

# 1回で処理する語数の上限。1語あたり最悪3分（リトライ＋90秒タイムアウト）なので、
# 20語で最悪1時間。これ以上増やすと1回が長くなりすぎ、途中でスリープに入る
# 可能性も上がる。語数がこれを超えるジャンル構成では、一周に複数日かかる。
MAX_BATCH = 20


def auto_batch(total):
    """
    1日3回の実行で全キーワードを一周する語数。設定の語数から決める。

    固定値にすると、ジャンルを減らしたとき1回で全部回ってしまい（負荷が偏る）、
    増やしたときは一周に何日もかかるのに気づけない。
    """
    if total <= 0:
        return 0
    return max(1, min(MAX_BATCH, -(-total // RUNS_PER_DAY)))

# 保存する投稿フィールド。スクレイパが返すキーと一致させてある。
POST_FIELDS = ("id", "text", "username", "timestamp", "permalink", "like_count")


def load_store():
    """既存の蓄積データを読む。無ければ空の構造を返す。"""
    if not DATA_FILE.exists():
        return {"posts": {}}
    try:
        store = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"data/posts.json が壊れています ({e})。\n"
            f"手動で確認するか、退避してから再実行してください: {DATA_FILE}"
        )
    store.setdefault("posts", {})
    return store


def save_store(store):
    """蓄積データを書き出す。書き込み中の中断で壊さないよう一時ファイル経由。"""
    store["updated_at"] = now_jst_iso()
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


def merge_posts(store, api_posts, genre, keyword, collected_at):
    """
    取得した投稿を store にマージする。副作用は store への書き込みのみ。
    返り値は (新規件数, 更新件数)。
    """
    new_count = 0
    updated_count = 0

    for raw in api_posts:
        post_id = raw.get("id")
        if not post_id:
            continue

        existing = store["posts"].get(post_id)
        if existing is None:
            record = {f: raw.get(f) for f in POST_FIELDS}
            record["genres"] = [genre]
            record["keywords"] = [keyword]
            record["first_seen"] = collected_at
            record["last_updated"] = collected_at
            store["posts"][post_id] = record
            new_count += 1
            continue

        # 既存投稿: いいね数など変わりうる値を最新で上書きする
        for f in POST_FIELDS:
            if raw.get(f) is not None:
                existing[f] = raw[f]
        if genre not in existing["genres"]:
            existing["genres"].append(genre)
        if keyword not in existing["keywords"]:
            existing["keywords"].append(keyword)
        existing["last_updated"] = collected_at
        updated_count += 1

    return new_count, updated_count


def build_pairs(config):
    """
    設定を [(ジャンル, キーワード), ...] に開く。
    設定ファイルに書いた順序が、そのまま収集の順序になる。
    """
    pairs = []
    for genre, entry in config.get("genres", {}).items():
        # 旧形式（配列そのもの）も読めるようにしておく
        keywords = entry if isinstance(entry, list) else entry.get("keywords", [])
        for keyword in keywords:
            pairs.append((genre, keyword))
    return pairs


def genres_with_data(store):
    """蓄積に1件でもある ジャンル名の集合を返す。"""
    seen = set()
    for post in store.get("posts", {}).values():
        seen.update(post.get("genres") or [])
    return seen


def load_seen():
    """
    これまでに収集へ回したキーワードの集合。記録が無ければ None を返す。

    None（初回）と空集合（全部が新規）は意味が違う。初回に空集合を返すと
    50語すべてが「新しい語」に見えて、1回で全部回そうとしてしまう。
    """
    if not SEEN_FILE.exists():
        return None
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, list):
        return None
    return {tuple(x) for x in data if isinstance(x, list) and len(x) == 2}


def seen_from_store(store, pairs):
    """
    記録ファイルがまだ無いとき、蓄積データから「一度は回した語」を割り出す。

    投稿に付いているキーワードは、その語で実際に検索して拾えた証拠になる。
    これをやらないと、記録を作る前に足し引きした語が先回りから漏れる。
    一度も投稿を取れていない語は「まだ回していない」扱いになるが、
    その回のバッチに入った時点で記録に載るので、一周すれば落ち着く。
    """
    collected = set()
    for post in store.get("posts", {}).values():
        collected.update(post.get("keywords") or [])
    return {p for p in pairs if p[1] in collected}


def save_seen(seen, pairs, batch_pairs):
    """
    記録を更新する。今回回した分を足し、設定から消えた語は落とす。

    落としておくと、いったん消して書き戻した語をまた「新しい語」として
    拾える。残したままだと、書き戻しても先回りが効かない。
    """
    base = set(pairs) if seen is None else seen
    updated = sorted((base | set(batch_pairs)) & set(pairs))
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SEEN_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps([list(p) for p in updated], ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(SEEN_FILE)


def load_rotation():
    """前回どこまで進んだかを読む。無い・壊れているなら空を返して先頭から始める。"""
    if not ROTATION_FILE.exists():
        return {}
    try:
        state = json.loads(ROTATION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return state if isinstance(state, dict) else {}


def save_rotation(genre, keyword):
    """次回の開始位置を記録する。書き込み中の中断で壊さないよう一時ファイル経由。"""
    ROTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROTATION_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {"last_genre": genre, "last_keyword": keyword, "updated_at": now_jst_iso()},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    tmp.replace(ROTATION_FILE)


def select_batch(pairs, state, batch):
    """
    今回処理する分を、前回の続きから batch 件だけ切り出す。
    末尾まで来たら先頭に戻る。返り値は (切り出した組, 開始位置)。

    位置の番号ではなく「前回最後に処理したキーワード」を覚えて探し直している。
    設定ファイルにジャンルを足し引きしても位置がずれず、見つからなければ
    先頭から再開するだけで済むため。
    """
    if not pairs:
        return [], 0
    if batch <= 0 or batch >= len(pairs):
        return list(pairs), 0

    last = (state.get("last_genre"), state.get("last_keyword"))
    try:
        start = (pairs.index(last) + 1) % len(pairs)
    except ValueError:
        start = 0

    doubled = pairs + pairs
    return doubled[start:start + batch], start


def stale_genres(store, config_genres):
    """
    蓄積に残っているのに、設定にはもう無いジャンル名を数える。
    {ジャンル名: 件数} を件数の多い順で返す。

    設定のジャンル名だけ変えて蓄積を放置すると、ページに新旧のチップが
    両方並び、どちらを押しても半分しか出てこない状態になる。
    付け替えは名前の対応を機械では決められないので、警告だけ出す。
    """
    if not config_genres:
        return {}
    counts = {}
    known = set(config_genres)
    for post in store.get("posts", {}).values():
        for genre in post.get("genres") or []:
            if genre not in known:
                counts[genre] = counts.get(genre, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def warn_stale_genres(store, config_genres):
    """ズレを見つけたら、直し方まで含めて画面とログに出す。黙って放置しない。"""
    stale = stale_genres(store, config_genres)
    if not stale:
        return
    print("\n[注意] 設定に無いジャンル名が蓄積に残っています。")
    print("       ページに新旧のチップが両方並びます。")
    for genre, count in stale.items():
        print(f"  - {genre}: {count} 件")
    print("  ジャンル名を変えたなら、蓄積側も付け替えてください:")
    print(f"    python3 scripts/rename_genre.py '{next(iter(stale))}' '<新しい名前>'")


def failed_pairs(raw):
    """
    スクレイパの結果から、失敗した (ジャンル, キーワード) を拾う。

    失敗した語を「回した語」に数えると、次の実行で先回りの対象から外れて
    しまう。ネットワークが切れて後半が全滅した回でも、次に真っ先に
    掛け直せるようにするため、成功した語だけを記録する。
    """
    return {(e.get("genre"), e.get("keyword"))
            for e in raw.get("results", []) if e.get("error")}


def plan_batch(pairs, state, batch, seen):
    """
    今回処理する組を決める。返り値は (処理する組, ローテーションで進んだ窓, 開始位置)。

    設定に足したばかりの語は、ローテーションが一周するのを待たずに先頭へ入れる。
    キーワードを直したら次の自動実行で反映されるようにするため（待つと最大1日）。
    そのぶんローテーション側の枠を削るので、1回の語数は変わらない。

    ローテーションの位置は「窓」の最後で進める。新しい語が窓と重なって
    実際には回さなかった語も、窓に入っていれば済んだものとして扱う。
    """
    if not pairs:
        return [], [], 0
    if batch <= 0 or batch >= len(pairs):
        return list(pairs), list(pairs), 0

    fresh = [] if seen is None else [p for p in pairs if p not in seen]
    fresh = fresh[:batch]

    room = batch - len(fresh)
    if room <= 0:
        # 新しい語だけで枠が埋まった。残りは次回に回るので位置は進めない
        return fresh, [], None

    window, start = select_batch(pairs, state, room)
    fresh_set = set(fresh)
    rest = [p for p in window if p not in fresh_set]
    return fresh + rest, window, start


def write_batch_config(config, batch_pairs, path):
    """
    今回処理する分だけを抜き出した設定ファイルを書く。scrape.mjs はこれを読む。
    required_any は元の設定から引き継ぐので、関連度フィルタの強さは変わらない。
    返り値は書き出したジャンルの辞書（画面表示に使う）。
    """
    source = config.get("genres", {})
    genres = {}
    for genre, keyword in batch_pairs:
        entry = source.get(genre, {})
        required = [] if isinstance(entry, list) else entry.get("required_any", [])
        slot = genres.setdefault(genre, {"keywords": [], "required_any": required})
        if keyword not in slot["keywords"]:
            slot["keywords"].append(keyword)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"genres": genres}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return genres


def load_config_genre_names():
    """設定にあるジャンル名。読めなければ空を返し、ズレの警告はしない。"""
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(config.get("genres", {}))


def load_required_any():
    """ジャンルごとの必須語を読む。{ジャンル名: [語, ...]} を返す。"""
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    table = {}
    for genre, entry in config.get("genres", {}).items():
        # 旧形式（配列そのもの）には必須語が無いので、フィルタなし扱いにする
        table[genre] = [] if isinstance(entry, list) else entry.get("required_any", [])
    return table


def is_relevant(text, required_any):
    """
    本文が必須語のどれかを含むか。必須語が空ならフィルタしない。

    Threadsの検索は語が緩く一致するため、『つむじ 薄い』が妊娠検査薬の
    『薄い』に反応するような取りこぼしが起きる。それを落とすための関門。
    """
    if not required_any:
        return True
    body = text or ""
    return any(word in body for word in required_any)


# launchd から起動されると PATH が /usr/bin:/bin:/usr/sbin:/sbin だけになり、
# /usr/local/bin にある node が見つからない。よくある場所を直接探す。
NODE_CANDIDATES = (
    "/usr/local/bin/node",
    "/opt/homebrew/bin/node",
    "/usr/bin/node",
)


def find_node():
    """node の実行ファイルを探す。PATH に無くても既知の場所を当たる。"""
    node = shutil.which("node")
    if node:
        return node
    for path in NODE_CANDIDATES:
        if os.access(path, os.X_OK):
            return path
    # nvm で入れている場合はバージョンごとのディレクトリに入る
    nvm = Path.home() / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        for version in sorted(nvm.iterdir(), reverse=True):
            candidate = version / "bin" / "node"
            if os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def require_node():
    """node が使えるか確かめる。無ければ分かる形で止める。"""
    node = find_node()
    if not node:
        raise SystemExit(
            "node が見つかりません。Playwright の実行に必要です。\n"
            f"  探した場所: PATH, {', '.join(NODE_CANDIDATES)}, ~/.nvm/versions/node/*/bin/node\n"
            "  Node.js を入れてから再実行してください: https://nodejs.org/"
        )
    if not (BASE_DIR / "node_modules" / "playwright").exists():
        raise SystemExit(
            "playwright が入っていません。プロジェクト直下で次を実行してください:\n"
            f"  npm install --prefix {BASE_DIR} playwright"
        )
    return node


def run_scraper(node, extra_args):
    """scrape.mjs を実行する。出力はそのまま画面に流す。"""
    cmd = [node, str(SCRAPER)] + extra_args
    print(f"$ {' '.join(cmd)}\n")
    return subprocess.run(cmd, cwd=str(BASE_DIR)).returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true",
                        help="ブラウザを開いてThreadsにログインする（初回のみ）")
    parser.add_argument("--genre", help="このジャンルのみ収集する（ローテーションは進めない）")
    parser.add_argument("--all", action="store_true",
                        help="ローテーションせず全ジャンルを1回で回す（数時間かかる）")
    parser.add_argument("--missing", action="store_true",
                        help="まだ1件も集まっていないジャンルだけ収集する")
    parser.add_argument("--batch", type=int, default=None,
                        help="1回で処理するキーワード数（既定は1日3回で一周する数／0で全部）")
    parser.add_argument("--limit", type=int, default=0,
                        help="先頭N個のキーワードだけ処理する（試運転用。ローテーションは進めない）")
    parser.add_argument("--delay", type=float, default=5.0,
                        help="キーワード間の待機秒数（既定5秒）")
    parser.add_argument("--headful", action="store_true", help="ブラウザを表示する")
    parser.add_argument("--dump-dir", help="生レスポンスを保存する（原因調査用）")
    parser.add_argument("--dry-run", action="store_true", help="保存せず件数だけ表示する")
    parser.add_argument("--no-filter", action="store_true",
                        help="関連度フィルタをかけずに全部保存する")
    parser.add_argument("--from-raw", type=Path,
                        help="スクレイピングせず、既存のraw JSONからマージし直す")
    args = parser.parse_args()

    if args.login:
        node = require_node()
        return run_scraper(node, ["--login"])

    # --- 投稿を用意する（スクレイピング or 既存rawの読み直し） ---
    if args.from_raw:
        raw_path = args.from_raw
        if not raw_path.exists():
            raise SystemExit(f"指定されたファイルがありません: {raw_path}")
    else:
        node = require_node()
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        pairs = build_pairs(config)
        if not pairs:
            raise SystemExit(f"キーワードが1つもありません: {CONFIG_FILE}")
        seen = load_seen()
        if seen is None:
            seen = seen_from_store(load_store(), pairs)
        window = []
        batch = args.batch if args.batch is not None else auto_batch(len(pairs))

        # --- 今回どこを回すか決める ---
        if args.genre:
            if args.genre not in config.get("genres", {}):
                raise SystemExit(
                    f"ジャンル '{args.genre}' が {CONFIG_FILE} にありません。\n"
                    f"  あるジャンル: {' / '.join(config.get('genres', {}))}"
                )
            batch_pairs = [p for p in pairs if p[0] == args.genre]
            advance = False
        elif args.missing:
            # ジャンルを増やした直後、ローテーションが一周するのを待たずに
            # 空のジャンルだけ埋めたいときに使う
            have = genres_with_data(load_store())
            batch_pairs = [p for p in pairs if p[0] not in have]
            advance = False
            if not batch_pairs:
                raise SystemExit(
                    "すべてのジャンルに1件以上あります。--missing で集めるものはありません。"
                )
            print(f"未収集の {len({g for g, _ in batch_pairs})} ジャンル / "
                  f"{len(batch_pairs)} 語を処理します（--missing）")
        elif args.all:
            batch_pairs = pairs
            advance = False
            print(f"全 {len(pairs)} 語を1回で処理します（--all）。数時間かかります。")
        else:
            batch_pairs, window, start = plan_batch(
                pairs, load_rotation(), batch, seen
            )
            advance = bool(window)
            fresh_count = 0 if seen is None else len([p for p in batch_pairs if p not in seen])
            if start is None:
                print(f"設定に足したばかりの {len(batch_pairs)} 語を先に処理します"
                      f"（ローテーションは進めません）")
            else:
                print(f"ローテーション: 全 {len(pairs)} 語のうち "
                      f"{start + 1} 番目から {len(window)} 語を処理します")
                if fresh_count:
                    print(f"うち {fresh_count} 語は設定に足したばかりの語なので先に回します")

        # 試運転で先頭だけ切ると、最後まで進んでいないのに位置だけ進んでしまう。
        # 「回した語」の記録も同じ理由で残さない
        if args.limit:
            advance = False

        genres = write_batch_config(config, batch_pairs, BATCH_FILE)
        print("今回のジャンル: " + " / ".join(
            f"{g}({len(v['keywords'])}語)" for g, v in genres.items()))

        scraper_args = [
            "--keywords", str(BATCH_FILE),
            "--out", str(RAW_FILE),
            "--delay", str(args.delay),
        ]
        if args.limit:
            scraper_args += ["--limit", str(args.limit)]
        if args.headful:
            scraper_args.append("--headful")
        if args.dump_dir:
            scraper_args += ["--dump-dir", args.dump_dir]

        code = run_scraper(node, scraper_args)
        if code != 0 or not RAW_FILE.exists():
            print("\n[NG] 収集に失敗しました。蓄積データは変更していません。")
            if advance:
                print("     ローテーションも進めていないので、次回は同じ範囲をやり直します。")
            return 1

        raw_path = RAW_FILE
        failed = failed_pairs(json.loads(raw_path.read_text(encoding="utf-8")))
        if failed:
            print(f"\n失敗した {len(failed)} 語は「回した語」に数えません"
                  f"（次の実行で先に掛け直します）。")

        # 一部のキーワードが失敗しても位置は進める。詰まったジャンルで
        # 止まり続けると、その先のジャンルが永久に収集されなくなるため。
        if not args.dry_run and not args.limit:
            if advance:
                save_rotation(*window[-1])
            save_seen(seen, pairs, [p for p in batch_pairs if p not in failed])

    # --- マージ ---
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    store = load_store()
    before = len(store["posts"])
    collected_at = now_jst_iso()

    required_table = {} if args.no_filter else load_required_any()

    total_new = 0
    total_updated = 0
    total_dropped = 0
    dropped_samples = []
    failures = []

    for entry in raw.get("results", []):
        if entry.get("error"):
            failures.append((entry.get("keyword"), entry["error"]))
            continue

        genre = entry.get("genre", "不明")
        required_any = required_table.get(genre, [])
        kept = []
        for post in entry.get("posts", []):
            if is_relevant(post.get("text"), required_any):
                kept.append(post)
            else:
                total_dropped += 1
                if len(dropped_samples) < 5:
                    text = (post.get("text") or "").replace("\n", " ")[:50]
                    dropped_samples.append(f"@{post.get('username')}: {text}")

        new_count, updated_count = merge_posts(
            store, kept, genre, entry.get("keyword", "不明"), collected_at,
        )
        total_new += new_count
        total_updated += updated_count

    print("\n" + "-" * 50)
    print(f"新規: {total_new} 件 / 更新: {total_updated} 件")
    if total_dropped:
        print(f"関連度フィルタで除外: {total_dropped} 件")
        for sample in dropped_samples:
            print(f"  - {sample}")
        if total_dropped > len(dropped_samples):
            print(f"  ... ほか {total_dropped - len(dropped_samples)} 件")
    print(f"蓄積合計: {before} → {len(store['posts'])} 件")

    if failures:
        print(f"\n失敗したキーワード: {len(failures)}")
        for kw, msg in failures:
            print(f"  - {kw}: {msg}")

    warn_stale_genres(store, load_config_genre_names())

    if args.dry_run:
        print("\n--dry-run のため保存しませんでした。")
        return 0

    if len(store["posts"]) == before and total_updated == 0:
        print("\n[NG] 1件も取れなかったため保存しません。")
        print("     --dump-dir data/dump を付けて再実行すると、生レスポンスを確認できます。")
        return 1

    save_store(store)
    print(f"\n保存しました: {DATA_FILE}")
    print("次: python3 scripts/build_html.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
