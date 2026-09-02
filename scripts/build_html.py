#!/usr/bin/env python3
"""
data/posts.json を読んで、単一ファイル完結の HTML 一覧を out/index.html に書き出す。

外部リソースを一切参照しないので、ブラウザで開くだけで動く（サーバー不要）。

並び替えは2種類:
  - いいね数        : 絶対値。定番の強い投稿が上位に来る
  - 時間あたりいいね : like_count / 経過時間。今まさに伸びている投稿が上位に来る
    投稿直後の過大評価を防ぐため、経過時間は最低 VELOCITY_FLOOR_HOURS として計算する

使い方:
  python3 scripts/build_html.py
  python3 scripts/build_html.py --output /path/to/out.html
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BASE_DIR, CONFIG_FILE, DATA_FILE, JST, now_jst_iso, parse_timestamp,
)

# GitHub Pages は main ブランチの /docs をそのまま配信できるので、ここに出す
OUTPUT_FILE = BASE_DIR / "docs" / "index.html"

# 投稿直後の数件で velocity が跳ね上がるのを防ぐための下限（時間）
VELOCITY_FLOOR_HOURS = 6.0

# ページに載せる範囲。data/posts.json には全履歴が残り、ここで絞るのは表示分だけ。
# 無制限にするとHTMLが際限なく太り、GitHubの1ファイル上限に当たって更新が止まる。
DEFAULT_MAX_AGE_DAYS = 180
DEFAULT_MAX_POSTS = 1500

# 各ジャンルに必ず確保する枠。
# 上限を全体の順位だけで切ると、いいね数の絶対値が大きいジャンル（ダイエットなど）が
# 枠を食い切り、ニッチなジャンル（神経エステなど）がページから消える。
DEFAULT_PER_GENRE = 80


def build_rows(store, now=None):
    """蓄積データを、HTML に埋め込む行のリストに変換する。"""
    now = now or datetime.now(JST)
    rows = []

    for post_id, p in store.get("posts", {}).items():
        likes = p.get("like_count")
        likes = likes if isinstance(likes, int) else 0

        posted = parse_timestamp(p.get("timestamp"))
        if posted is None:
            age_hours = None
            velocity = 0.0
            posted_iso = ""
        else:
            age_hours = (now - posted).total_seconds() / 3600.0
            velocity = likes / max(age_hours, VELOCITY_FLOOR_HOURS)
            posted_iso = posted.astimezone(JST).isoformat()

        rows.append({
            "id": post_id,
            "username": p.get("username") or "unknown",
            "text": p.get("text") or "",
            "permalink": p.get("permalink") or "",
            "likes": likes,
            "velocity": round(velocity, 2),
            "ageHours": round(age_hours, 1) if age_hours is not None else None,
            "postedAt": posted_iso,
            "genres": p.get("genres") or [],
            "keywords": p.get("keywords") or [],
        })

    rows.sort(key=lambda r: r["likes"], reverse=True)
    return rows


def embed_json(data):
    """<script> の中に安全に置ける JSON 文字列にする。"""
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def take_top(rows, quota, chosen):
    """
    rows の上位 quota 件を chosen（id → 行）に足す。すでに入っている分も枠に数える。

    いいね順だけで切ると「新しくて急上昇中だがまだ総数が少ない投稿」が落ちる。
    逆に伸び順だけで切ると定番の強い投稿が落ちる。そこで両方の上位を
    半分ずつ確保してから、残りをいいね順で埋める。
    """
    if quota <= 0:
        return
    already = sum(1 for r in rows if r["id"] in chosen)
    room = quota - already
    if room <= 0:
        return

    half = room // 2
    by_likes = sorted(rows, key=lambda r: -r["likes"])
    by_velocity = sorted(rows, key=lambda r: -r["velocity"])

    added = 0
    for pool, limit in ((by_velocity, half), (by_likes, room)):
        for r in pool:
            if added >= limit:
                break
            if r["id"] in chosen:
                continue
            chosen[r["id"]] = r
            added += 1


def select_rows(rows, max_age_days, max_posts, per_genre=DEFAULT_PER_GENRE):
    """
    ページに載せる投稿を選ぶ。返り値は (選んだ行, 期間外で外した数, 上限で外した数)。

    全体の順位だけで上限まで切ると、いいね数の絶対値が大きいジャンルが枠を
    食い切り、ニッチなジャンルがページから丸ごと消える。そこで先に
    ジャンルごとの枠を確保し、残りを全体の上位で埋める。
    """
    if max_age_days > 0:
        limit_hours = max_age_days * 24
        # 投稿日時が取れなかったものは判断できないので残す
        in_window = [r for r in rows if r["ageHours"] is None or r["ageHours"] <= limit_hours]
    else:
        in_window = list(rows)
    aged_out = len(rows) - len(in_window)

    if max_posts <= 0 or len(in_window) <= max_posts:
        return in_window, aged_out, 0

    # --- 1. ジャンルごとの枠 ---
    by_genre = {}
    for r in in_window:
        for g in r.get("genres") or []:
            by_genre.setdefault(g, []).append(r)

    chosen = {}
    if per_genre > 0 and by_genre:
        # 枠の合計が上限を超えるとジャンルの並び順で後ろが切り捨てられる。
        # そうならないよう、超えるときは全ジャンルを均等に縮める。
        quota = min(per_genre, max(1, max_posts // len(by_genre)))
        # 件数の少ないジャンルから埋める。多いジャンルが先に枠を取ると、
        # 掛け持ち投稿で少ないジャンルの枠が食われて0件になりうる。
        for _, genre_rows in sorted(by_genre.items(), key=lambda kv: len(kv[1])):
            if len(chosen) >= max_posts:
                break
            take_top(genre_rows, quota, chosen)

    # --- 2. 残りを全体の上位で埋める ---
    take_top(in_window, max_posts, chosen)

    selected = list(chosen.values())[:max_posts]
    return selected, aged_out, len(in_window) - len(selected)


def load_config_genres(path):
    """
    設定にあるジャンル名を、書かれた順に返す。

    ページには「まだ集まっていないジャンル」も出す。データにあるものだけを
    並べると、ローテーションで今日まだ回っていないジャンルが消えてしまい、
    対象が狭まったように見えるため。読めなければ空を返し、データ側だけで組む。
    """
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(config.get("genres", {}))


def rising_threshold(rows):
    """
    「伸び中」と表示する基準。全投稿の velocity の上位10%にあたる値を使う。
    固定値だとジャンルや時期で意味が変わってしまうため、母集団から決める。
    """
    values = sorted((r["velocity"] for r in rows if r["velocity"] > 0), reverse=True)
    if not values:
        return float("inf")
    index = max(0, int(len(values) * 0.10) - 1)
    return values[index]


def build_summary(rows, store, archived, config_genres=()):
    """一覧の上に出す集計。詳細より先に全体像が分かるようにする。"""
    counts = {}
    for r in rows:
        for g in r["genres"]:
            counts[g] = counts.get(g, 0) + 1

    # 集まっているものを件数の多い順に、まだ0件のものを設定に書いた順で後ろに置く。
    # 「今どのジャンルが強いか」が先に見え、未収集は下にまとまって読みやすい。
    collected = sorted(
        ((g, n) for g, n in counts.items() if n > 0), key=lambda kv: (-kv[1], kv[0])
    )
    pending = [(g, 0) for g in config_genres if counts.get(g, 0) == 0]

    week = [r for r in rows if r["ageHours"] is not None and r["ageHours"] <= 168]
    return {
        "total": len(rows),
        "archived": archived,
        "genres": collected + pending,
        "over1000": len([r for r in rows if r["likes"] >= 1000]),
        "thisWeek": len(week),
        "authors": len({r["username"] for r in rows}),
        "updatedAt": (store.get("updated_at") or "")[:16].replace("T", " "),
    }


def render_html(rows, generated_at, store, archived, config_genres=()):
    summary = build_summary(rows, store, archived, config_genres)
    # チップの並びは下の「ジャンル別」の棒グラフと揃える
    genres = [[name, count] for name, count in summary["genres"]]
    keywords = sorted({k for r in rows for k in r["keywords"]})

    return (
        TEMPLATE.replace("__DATA__", embed_json(rows))
        .replace("__GENRES__", embed_json(genres))
        .replace("__KEYWORDS__", embed_json(keywords))
        .replace("__SUMMARY__", embed_json(summary))
        .replace("__RISING__", str(round(rising_threshold(rows), 4)))
        .replace("__GENERATED__", generated_at)
        .replace("__GENRE_COUNT__", str(len(genres)))
        .replace("__COUNT__", str(len(rows)))
    )


TEMPLATE = r"""
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- 公開リポジトリで配信するため、検索結果には出さない -->
<meta name="robots" content="noindex, nofollow">
<title>Threads Research Tool（美容ジャンル ver）</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zen+Old+Mincho:wght@600;900&family=Roboto+Mono:wght@400;500;700&display=swap">
<style>
  /* 明るい側を基準に全トークンを定義する。暗い側は下で上書きする。 */
  :root {
    --bg: #f6f4f5;
    --surface: #ffffff;
    --surface-2: #fbf9fa;
    --ink: #231c22;
    --muted: #6f636c;
    --border: #e4dee2;
    --accent: #8b2f5f;
    --accent-soft: #f7e9f0;
    --rising: #0f7b6c;
    --rising-soft: #e2f2ef;
    --chip: #efeaed;
    --focus: #8b2f5f;
  }
  /* OS が暗いとき。ただし閲覧者が明るいテーマを選んでいたらそちらを優先する。 */
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #151114;
      --surface: #1f1a1e;
      --surface-2: #241e23;
      --ink: #f0eaee;
      --muted: #a3969e;
      --border: #332b31;
      --accent: #e086b0;
      --accent-soft: #3a2130;
      --rising: #4fc3ae;
      --rising-soft: #16332e;
      --chip: #2c2429;
      --focus: #e086b0;
    }
  }
  /* 閲覧者が暗いテーマを選んだとき。OS の設定に関係なく効かせる。 */
  :root[data-theme="dark"] {
    --bg: #151114;
    --surface: #1f1a1e;
    --surface-2: #241e23;
    --ink: #f0eaee;
    --muted: #a3969e;
    --border: #332b31;
    --accent: #e086b0;
    --accent-soft: #3a2130;
    --rising: #4fc3ae;
    --rising-soft: #16332e;
    --chip: #2c2429;
    --focus: #e086b0;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    /* 透明のままだと閲覧側の地の色を借りてしまうので必ず塗る */
    background: var(--bg);
    color: var(--ink);
    /* 日本語本文はWebフォントを落とすと重いので、端末のフォントを使う */
    font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP",
                 -apple-system, BlinkMacSystemFont, "Yu Gothic Medium", sans-serif;
    line-height: 1.75;
    font-feature-settings: "palt" 1;
    word-break: normal;
    overflow-wrap: break-word;
    line-break: strict;
  }

  .wrap { max-width: 880px; margin: 0 auto; padding: 40px 20px 96px; }

  :focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
    border-radius: 4px;
  }

  /* --- 見出し --- */
  h1 {
    font-family: "Zen Old Mincho", "Hiragino Mincho ProN", "Yu Mincho", serif;
    font-weight: 900;
    font-size: clamp(1.5rem, 4vw, 2.1rem);
    line-height: 1.35;
    letter-spacing: .01em;
    margin: 0;
    text-wrap: balance;
  }
  /* 対象ジャンルの但し書き。名前より一段弱く見せる */
  .ver {
    display: block;
    font-family: "Hiragino Sans", "Noto Sans JP", sans-serif;
    font-weight: 400;
    font-size: .74rem;
    letter-spacing: .02em;
    color: var(--muted);
    margin-top: 6px;
  }

  /* --- 集計：詳細より先に全体像を出す --- */
  .panel {
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    background: var(--surface);
    margin: 28px 0 8px;
  }
  /* 4枚で固定する。auto-fit だと枚数によって最後の1枚だけ次の行に
     取り残され、空いた枠が塗り残しに見えてしまうため。 */
  .summary {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1px;
    background: var(--border);
  }
  @media (max-width: 620px) {
    /* 4枚なので2列でもきれいに埋まる */
    .summary { grid-template-columns: repeat(2, 1fr); }
  }
  .stat { background: var(--surface); padding: 14px 16px; }

  /* --- ジャンル別の内訳 --- */
  /* 棒にしておけば、ジャンルが何個あっても1行1本で並ぶので取り残しが出ない */
  .breakdown { padding: 15px 16px 17px; border-top: 1px solid var(--border); }
  .breakdown-title {
    font-size: .7rem; color: var(--muted); letter-spacing: .06em;
    margin: 0 0 11px; white-space: nowrap;
  }
  /* 名前の列は固定幅。名前に合わせて伸ばすと、長いジャンルの行だけ棒の
     開始位置がずれて、棒どうしの長さを目で比べられなくなる。
     収まらない名前は「・」の位置で2行に折る（折り位置は .nb で決め打ち）。
     8.5em は最長の区切り「リラクゼーション」8文字が1行に収まる幅。 */
  .bar-row {
    display: grid;
    grid-template-columns: 8.5em 1fr auto;
    gap: 12px; align-items: center;
  }
  .bar-row + .bar-row { margin-top: 8px; }
  /* 1行で収まる名前も2行の名前と同じ高さにする。混ざると行の間隔が
     ばらついて、棒の並びが読みにくくなる。
     flex にしているのは、折り返した2行をまとめて上下中央に置くため。 */
  .bar-name {
    font-size: .76rem; line-height: 1.4;
    min-height: 2.8em;
    display: flex; flex-wrap: wrap; align-content: center;
  }
  .bar-track {
    height: 6px; border-radius: 999px;
    background: var(--chip); overflow: hidden;
  }
  .bar-fill { height: 100%; border-radius: 999px; background: var(--accent); }
  .bar-count {
    font-family: "Roboto Mono", ui-monospace, monospace;
    font-size: .74rem; color: var(--muted);
    font-variant-numeric: tabular-nums; white-space: nowrap;
  }
  @media (max-width: 620px) {
    /* 幅は変えない。変えると狭い画面だけ折り返し位置が変わってしまう */
    .bar-row { gap: 9px; }
  }
  /* まだ集まっていないジャンル。対象には入っているので消さず、弱く見せる */
  .bar-row.pending .bar-name { color: var(--muted); }
  .bar-row.pending .bar-track { opacity: .55; }
  /* 「収集待ち」は日本語なので、等幅フォントに任せず本文と同じ書体で出す */
  .bar-row.pending .bar-count {
    font-family: "Hiragino Sans", "Noto Sans JP", sans-serif;
    font-size: .7rem;
  }
  .stat-label {
    font-size: .7rem; color: var(--muted); letter-spacing: .06em;
    display: block; margin-bottom: 4px;
    /* 「表示中/の投稿」のように助詞で割れないよう、まとめて扱う */
    white-space: nowrap;
  }
  .stat-value {
    white-space: nowrap;
    font-family: "Roboto Mono", ui-monospace, monospace;
    font-size: 1.25rem; font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1.2;
  }
  .stat-value .unit { font-size: .72rem; font-weight: 400; color: var(--muted); margin-left: 3px; }
  .stamp {
    font-family: "Roboto Mono", ui-monospace, monospace;
    font-size: .7rem; color: var(--muted); margin: 0 0 26px;
  }

  /* --- 操作バー --- */
  .controls {
    position: sticky; top: 0; z-index: 10;
    background: var(--bg);
    padding: 12px 0 14px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 18px;
  }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .row + .row { margin-top: 8px; }
  select, input[type=search] {
    font: inherit; font-size: .82rem;
    padding: 7px 11px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--surface);
    color: var(--ink);
  }
  input[type=search] { flex: 1; min-width: 180px; }
  .chip {
    display: inline-flex; align-items: baseline; gap: 6px;
    font-size: .78rem; padding: 5px 13px;
    border: 1px solid var(--border); border-radius: 999px;
    background: var(--surface); color: var(--muted);
    cursor: pointer; user-select: none;
  }
  .chip:hover { border-color: var(--accent); color: var(--accent); }
  .chip.on {
    background: var(--accent-soft); border-color: var(--accent);
    color: var(--accent); font-weight: 700;
  }
  /* ジャンル名は途中で割らない。「ダイエット」を「ダイ」と「エット」に分けない */
  .chip-name { white-space: nowrap; }
  /* まだ1件も無いジャンル。押しても空振りするので、選べないことを見た目で示す */
  .chip.pending {
    opacity: .45; cursor: default;
    border-style: dashed;
  }
  .chip.pending:hover { border-color: var(--border); color: var(--muted); }
  .count {
    white-space: nowrap;
    font-family: "Roboto Mono", ui-monospace, monospace;
    color: var(--muted); font-size: .76rem; margin-bottom: 14px;
    font-variant-numeric: tabular-nums;
  }

  /* --- カード --- */
  #list { display: flex; flex-direction: column; gap: 10px; }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid transparent;
    border-radius: 10px;
    padding: 16px 18px;
  }
  /* 伸びが速い投稿は左端の色で一目で分かるようにする */
  .card.rising { border-left-color: var(--rising); background: var(--surface-2); }

  .card-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 9px; }
  .rank {
    font-family: "Roboto Mono", ui-monospace, monospace;
    font-size: .74rem; color: var(--muted);
    font-variant-numeric: tabular-nums; min-width: 2.4em;
  }
  .user { font-weight: 700; font-size: .86rem; }
  .badge {
    white-space: nowrap;
    font-size: .66rem; font-weight: 700; letter-spacing: .04em;
    padding: 2px 8px; border-radius: 999px;
    background: var(--rising-soft); color: var(--rising);
  }
  .stats {
    margin-left: auto; display: flex; gap: 11px;
    font-family: "Roboto Mono", ui-monospace, monospace;
    font-size: .74rem; font-variant-numeric: tabular-nums;
  }
  .likes { color: var(--accent); font-weight: 700; }
  .vel { color: var(--rising); font-weight: 500; }
  .age { color: var(--muted); }

  .text {
    white-space: pre-wrap;
    /* word-break: break-word は単語の途中で割るので使わない。
       overflow-wrap なら、1語が行に収まらないときだけ割る。
       line-break: strict で日本語の禁則処理を厳しい方に寄せる。 */
    word-break: normal;
    overflow-wrap: break-word;
    line-break: strict;
    font-size: .92rem; margin: 0 0 12px;
  }

  /* 文節のかたまり。ここで囲った範囲は途中で改行されない。
     「を」「と」などの助詞が行頭に来るのを防ぐために使う。 */
  .nb { white-space: nowrap; }

  .tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .tag {
    white-space: nowrap;
    font-size: .7rem; padding: 3px 9px; border-radius: 4px;
    background: var(--chip); color: var(--muted);
  }
  .link {
    margin-left: auto; font-size: .76rem; color: var(--accent);
    text-decoration: none; font-weight: 700; white-space: nowrap;
  }
  .link:hover { text-decoration: underline; }

  .empty { text-align: center; color: var(--muted); padding: 64px 20px; font-size: .88rem; }
</style>

<div class="wrap">
  <header>
    <h1>Threads Research Tool<span class="ver"><span class="nb">美容ジャンル全般</span><span class="nb">（__GENRE_COUNT__ジャンル）</span></span></h1>
  </header>

  <div class="panel">
    <div class="summary" id="summary"></div>
    <div class="breakdown" id="breakdown"></div>
  </div>
  <p class="stamp" id="stamp"></p>

  <div class="controls">
    <div class="row">
      <select id="sort">
        <option value="velocity">並び: 伸びの速さ</option>
        <option value="likes">並び: いいね数</option>
        <option value="newest">並び: 新着順</option>
      </select>
      <select id="period">
        <option value="0">期間: 全期間</option>
        <option value="7">期間: 7日以内</option>
        <option value="30">期間: 30日以内</option>
      </select>
      <select id="keyword"><option value="">キーワード: すべて</option></select>
    </div>
    <div class="row">
      <input type="search" id="q" placeholder="本文・ユーザー名で絞り込み">
    </div>
    <div class="row" id="genres"></div>
  </div>

  <div class="count" id="count"></div>
  <div id="list"></div>
</div>

<script id="data" type="application/json">__DATA__</script>
<script id="genre-list" type="application/json">__GENRES__</script>
<script id="keyword-list" type="application/json">__KEYWORDS__</script>
<script id="summary-data" type="application/json">__SUMMARY__</script>
<script>
(function () {
  var readJSON = function (id) { return JSON.parse(document.getElementById(id).textContent); };
  var POSTS = readJSON('data');
  var GENRES = readJSON('genre-list');
  var KEYWORDS = readJSON('keyword-list');
  var SUMMARY = readJSON('summary-data');
  var RISING = __RISING__;   // 伸び率の上位10%にあたる値

  var activeGenres = new Set();
  var els = {
    sort: document.getElementById('sort'),
    period: document.getElementById('period'),
    keyword: document.getElementById('keyword'),
    q: document.getElementById('q'),
    genres: document.getElementById('genres'),
    list: document.getElementById('list'),
    count: document.getElementById('count'),
    summary: document.getElementById('summary'),
    breakdown: document.getElementById('breakdown')
  };

  function mk(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  // 文節を1かたまりとして置く。途中で改行されないので、
  // 「を」「と」などの助詞が行頭に来ることがなくなる。
  function phrases(parent, list) {
    list.forEach(function (t) { parent.appendChild(mk('span', 'nb', t)); });
    return parent;
  }

  // --- 集計 ---
  // タイルは必ず4枚。ジャンルはここに混ぜず、下の棒グラフで見せる。
  (function renderSummary() {
    var tiles = [
      ['表示中の投稿', SUMMARY.total, '件'],
      ['直近7日の投稿', SUMMARY.thisWeek, '件'],
      ['1000いいね超え', SUMMARY.over1000, '件'],
      ['投稿者', SUMMARY.authors, '人']
    ];
    tiles.forEach(function (t) {
      var box = mk('div', 'stat');
      box.appendChild(mk('span', 'stat-label', t[0]));
      var v = mk('div', 'stat-value', t[1].toLocaleString());
      v.appendChild(mk('span', 'unit', t[2]));
      box.appendChild(v);
      els.summary.appendChild(box);
    });
  })();

  // --- ジャンル別の内訳 ---
  // 棒の長さは最多ジャンルを100%とした相対値。1つの投稿が複数ジャンルに
  // 入ることがあり、合計が総数と一致しないため、全体に対する割合としては見せない。
  (function renderBreakdown() {
    if (!SUMMARY.genres.length) { els.breakdown.remove(); return; }

    els.breakdown.appendChild(mk('p', 'breakdown-title', 'ジャンル別'));
    var max = SUMMARY.genres.reduce(function (m, p) { return Math.max(m, p[1]); }, 0);

    // 「神経エステ・リラクゼーション」は固定幅の列に1行では収まらない。
    // 「・」の位置だけで折り、カタカナ語の途中では絶対に割らない。
    function nameParts(name) {
      var parts = name.split('・');
      return parts.map(function (t, i) {
        // 「・」は前の語にくっつける。行頭に落とさないため
        return i < parts.length - 1 ? t + '・' : t;
      });
    }

    SUMMARY.genres.forEach(function (pair) {
      var row = mk('div', 'bar-row');
      if (pair[1] === 0) row.classList.add('pending');
      row.appendChild(phrases(mk('span', 'bar-name'), nameParts(pair[0])));

      var track = mk('div', 'bar-track');
      var fill = mk('div', 'bar-fill');
      fill.style.width = (max > 0 ? (pair[1] / max) * 100 : 0) + '%';
      track.appendChild(fill);
      row.appendChild(track);

      // 数字は出さない。棒の長さで強弱は足りる。
      // まだ集まっていないものだけ、空の棒の理由が分かるよう言葉を添える
      row.appendChild(mk('span', 'bar-count', pair[1] === 0 ? '収集待ち' : ''));
      els.breakdown.appendChild(row);
    });
  })();

  // 何件のうち何件を見ているのかを明示する。
  // 「最終収集」は実際に収集した時刻。HTMLを作り直しただけでは進まない。
  (function renderStamp() {
    var stamp = document.getElementById('stamp');
    var collectedAt = SUMMARY.updatedAt || '__GENERATED__';
    var units = ['最終収集 ' + collectedAt];
    if (SUMMARY.archived > SUMMARY.total) {
      units.push('　/　蓄積 ' + SUMMARY.archived.toLocaleString() + ' 件のうち ');
      units.push(SUMMARY.total.toLocaleString() + ' 件を表示');
    }
    phrases(stamp, units);
  })();

  KEYWORDS.forEach(function (k) {
    var o = document.createElement('option');
    o.value = k; o.textContent = 'キーワード: ' + k;
    els.keyword.appendChild(o);
  });

  // --- ジャンルの絞り込み ---
  // 対象の10ジャンルを全部並べる。ローテーションで今日まだ回っていないジャンルを
  // 隠すと、扱う範囲が狭まったように見えるため。
  // ジャンルが10個並ぶので、どれを押したか数えなくても戻れる「すべて」を先頭に置く。
  var chipStates = [];

  function makeChip(label, onActivate) {
    var b = mk('span', 'chip');
    b.appendChild(mk('span', 'chip-name', label));
    if (onActivate) {
      b.tabIndex = 0;
      b.setAttribute('role', 'button');
      b.addEventListener('click', onActivate);
      b.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onActivate(); }
      });
    } else {
      // 1件も無いので押しても何も起きない。操作対象から外す
      b.classList.add('pending');
      b.setAttribute('aria-disabled', 'true');
      b.title = 'まだ収集していません';
    }
    els.genres.appendChild(b);
    return b;
  }

  function syncChips() {
    chipStates.forEach(function (s) {
      var on = s.isOn();
      s.el.classList.toggle('on', on);
      s.el.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  var allChip = makeChip('すべて', function () {
    activeGenres.clear();
    syncChips();
    render();
  });
  chipStates.push({ el: allChip, isOn: function () { return activeGenres.size === 0; } });

  GENRES.forEach(function (pair) {
    var g = pair[0];
    if (pair[1] === 0) { makeChip(g, null); return; }
    var chip = makeChip(g, function () {
      if (activeGenres.has(g)) activeGenres.delete(g);
      else activeGenres.add(g);
      syncChips();
      render();
    });
    chipStates.push({ el: chip, isOn: function () { return activeGenres.has(g); } });
  });

  syncChips();

  function fmtAge(h) {
    if (h === null || h === undefined) return '不明';
    if (h < 24) return Math.round(h) + '時間前';
    return Math.round(h / 24) + '日前';
  }

  function filtered() {
    var days = parseInt(els.period.value, 10);
    var kw = els.keyword.value;
    var q = els.q.value.trim().toLowerCase();

    return POSTS.filter(function (p) {
      if (days > 0) {
        if (p.ageHours === null || p.ageHours > days * 24) return false;
      }
      if (kw && p.keywords.indexOf(kw) === -1) return false;
      if (activeGenres.size > 0) {
        var hit = p.genres.some(function (g) { return activeGenres.has(g); });
        if (!hit) return false;
      }
      if (q) {
        var hay = (p.text + ' ' + p.username).toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });
  }

  function sorted(rows) {
    var mode = els.sort.value;
    var copy = rows.slice();
    if (mode === 'likes') copy.sort(function (a, b) { return b.likes - a.likes; });
    else if (mode === 'newest') copy.sort(function (a, b) {
      var av = a.ageHours === null ? Infinity : a.ageHours;
      var bv = b.ageHours === null ? Infinity : b.ageHours;
      return av - bv;
    });
    else copy.sort(function (a, b) { return b.velocity - a.velocity; });
    return copy;
  }

  function render() {
    var rows = sorted(filtered());
    els.count.textContent = rows.length + ' 件を表示';
    els.list.textContent = '';

    if (rows.length === 0) {
      // 「絞り込みを」を1かたまりにして、「を」が行頭に来ないようにする
      els.list.appendChild(phrases(mk('div', 'empty'), [
        '条件に合う投稿が', 'ありません。', '絞り込みを', '緩めてください。'
      ]));
      return;
    }

    var frag = document.createDocumentFragment();
    rows.forEach(function (p, i) {
      var isRising = p.velocity >= RISING;
      var card = mk('div', 'card' + (isRising ? ' rising' : ''));

      var head = mk('div', 'card-head');
      head.appendChild(mk('span', 'rank', String(i + 1)));
      head.appendChild(mk('span', 'user', '@' + p.username));
      if (isRising) head.appendChild(mk('span', 'badge', '伸び中'));

      var stats = mk('div', 'stats');
      stats.appendChild(mk('span', 'likes', p.likes.toLocaleString() + ' likes'));
      stats.appendChild(mk('span', 'vel', p.velocity.toFixed(1) + '/h'));
      stats.appendChild(mk('span', 'age', fmtAge(p.ageHours)));
      head.appendChild(stats);
      card.appendChild(head);

      card.appendChild(mk('p', 'text', p.text));

      var tags = mk('div', 'tags');
      p.genres.concat(p.keywords).forEach(function (t) {
        tags.appendChild(mk('span', 'tag', t));
      });
      if (p.permalink) {
        var a = mk('a', 'link', '元投稿を開く →');
        a.href = p.permalink;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        tags.appendChild(a);
      }
      card.appendChild(tags);
      frag.appendChild(card);
    });
    els.list.appendChild(frag);
  }

  [els.sort, els.period, els.keyword].forEach(function (el) {
    el.addEventListener('change', render);
  });
  els.q.addEventListener('input', render);

  render();
})();
</script>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    parser.add_argument("--input", type=Path, default=DATA_FILE,
                        help="読み込む蓄積データ（検証用に差し替えられる）")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                        help="この日数より古い投稿はページに載せない（0で無制限）")
    parser.add_argument("--max-posts", type=int, default=DEFAULT_MAX_POSTS,
                        help="ページに載せる最大件数（0で無制限）")
    parser.add_argument("--per-genre", type=int, default=DEFAULT_PER_GENRE,
                        help="各ジャンルに必ず確保する件数（0で枠取りなし）")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE,
                        help="ジャンル一覧を読む設定ファイル")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[NG] データがありません: {args.input}")
        print("     先に python3 scripts/collect.py を実行してください。")
        return 1

    store = json.loads(args.input.read_text(encoding="utf-8"))
    all_rows = build_rows(store)
    rows, aged_out, over_cap = select_rows(
        all_rows, args.max_age_days, args.max_posts, args.per_genre
    )
    rows.sort(key=lambda r: r["likes"], reverse=True)

    config_genres = load_config_genres(args.config)
    html = render_html(
        rows, now_jst_iso()[:16].replace("T", " "), store, len(all_rows), config_genres
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")

    size_kb = args.output.stat().st_size / 1024
    print(f"生成しました: {args.output}  （{len(rows)} 件 / {size_kb:.0f} KB）")
    # 黙って捨てない。何をどれだけ載せなかったかを必ず出す。
    if aged_out or over_cap:
        print(f"蓄積 {len(all_rows)} 件のうち、ページに載せなかった分:")
        if aged_out:
            print(f"  {args.max_age_days} 日より古い: {aged_out} 件")
        if over_cap:
            print(f"  上限 {args.max_posts} 件を超過: {over_cap} 件")
        print("  （data/posts.json には全件そのまま残っています）")
    print(f"開く: open {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
