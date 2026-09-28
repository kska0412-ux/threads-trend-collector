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
    BASE_DIR, CONFIG_FILE, DATA_FILE, JST, parse_timestamp,
)

# GitHub Pages は main ブランチの /docs をそのまま配信できるので、ここに出す
OUTPUT_FILE = BASE_DIR / "docs" / "index.html"

# 投稿直後の数件で velocity が跳ね上がるのを防ぐための下限（時間）
VELOCITY_FLOOR_HOURS = 6.0

# ページに載せる範囲。data/posts.json には全履歴が残り、ここで絞るのは表示分だけ。
# 無制限にするとHTMLが際限なく太り、GitHubの1ファイル上限に当たって更新が止まる。
# ページは検索して使うので、1ジャンルあたりの件数が薄いと検索しても数件しか出ない。
# 40ジャンルで1500件だと1ジャンル37件まで縮むため、3000件（約2MB）にしている。
DEFAULT_MAX_AGE_DAYS = 180
DEFAULT_MAX_POSTS = 3000

# 各ジャンルに必ず確保する枠。
# 上限を全体の順位だけで切ると、いいね数の絶対値が大きいジャンル（ダイエットなど）が
# 枠を食い切り、ニッチなジャンル（パーマネントジュエリーなど）がページから消える。
DEFAULT_PER_GENRE = 60


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


def rising_js(rows):
    """
    「伸び中」の基準を JavaScript の値として書き出す。

    投稿が0件のとき Python の float("inf") をそのまま str() すると "inf" になり、
    JS では未定義の識別子になってページのスクリプトが丸ごと止まる。
    収集を始める前や、期間で全部落ちたときに必ず通る道なので、ここで潰す。
    """
    value = rising_threshold(rows)
    if value == float("inf"):
        return "Infinity"
    return str(round(value, 4))


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


def search_genres(rows, config_genres=()):
    """
    検索窓の候補に出すジャンル名。設定に書いた順に、設定に無いが
    データに残っている名前を後ろに足す。

    タブとしては並べない。入力しかけたときの候補（datalist）と、
    ジャンル名で検索されたときの判定にだけ使う。
    まだ収集していないジャンルも候補に出す。対象に入っていることが分かるように。
    """
    names = list(config_genres)
    known = set(names)
    for r in rows:
        for g in r["genres"]:
            if g not in known:
                known.add(g)
                names.append(g)
    return names


def render_html(rows, config_genres=()):
    genres = search_genres(rows, config_genres)

    return (
        TEMPLATE.replace("__DATA__", embed_json(rows))
        .replace("__GENRES__", embed_json(genres))
        .replace("__RISING__", rising_js(rows))
        .replace("__GENRE_COUNT__", str(len(genres)))
        .replace("__COUNT__", str(len(rows)))
    )


TEMPLATE = r"""<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- 公開リポジトリで配信するため、検索結果には出さない -->
<meta name="robots" content="noindex, nofollow">
<!-- LINE などのアプリ内ブラウザは前に開いたページを覚えていて、更新後も古い版を
     出し続けることがある。1日3回更新するページなので、毎回取り直させる -->
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Threads Research Tool（美容ビジネス ver）</title>
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

  /* 集計タイルと最終収集の行は廃止した。見出しのすぐ下に検索窓を置く */
  header { margin-bottom: 22px; }

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
  .hint + .row { margin-top: 10px; }
  select, input[type=search] {
    font: inherit; font-size: .82rem;
    padding: 7px 11px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--surface);
    color: var(--ink);
  }
  /* 検索窓がこのページの主役。ジャンルのタブは置かず、調べたい語を打って探す */
  .search-row { flex-wrap: nowrap; }
  /* 候補の一覧を検索窓の真下に重ねるための枠 */
  .search-box { position: relative; flex: 1; min-width: 0; display: flex; }
  input[type=search] {
    flex: 1; min-width: 0; width: 100%;
    font-size: 1rem;
    padding: 11px 14px;
    border-width: 1.5px;
    border-color: var(--accent);
    border-radius: 10px;
  }
  .search-btn {
    font: inherit; font-size: .88rem; font-weight: 700;
    padding: 11px 18px;
    border: 0; border-radius: 10px;
    background: var(--accent); color: var(--surface);
    cursor: pointer; white-space: nowrap;
  }
  /* 収集ジャンルの候補。<datalist> は iPhone の Safari などで一覧が出ないので、
     自前で組んで検索窓の下に重ねる。どの端末でもタップで選べる */
  .suggest {
    position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 30;
    margin: 0; padding: 4px 0; list-style: none;
    /* min() を読めない古いアプリ内ブラウザ向けに、先に固定値を置く */
    max-height: 320px;
    max-height: min(50vh, 320px); overflow-y: auto;
    -webkit-overflow-scrolling: touch; overscroll-behavior: contain;
    background: var(--surface);
    border: 1px solid var(--border); border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, .14);
  }
  .suggest[hidden] { display: none; }
  .suggest-item {
    /* ジャンル名は途中で割らない */
    white-space: nowrap;
    font-size: .92rem; line-height: 1.4;
    padding: 11px 14px;
    cursor: pointer;
  }
  .suggest-item[hidden] { display: none; }
  .suggest-item:hover, .suggest-item.active { background: var(--accent-soft); color: var(--accent); }
  .hint {
    font-size: .74rem; color: var(--muted);
    margin: 8px 0 0; line-height: 1.6;
  }
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
    <h1>Threads Research Tool<span class="ver"><span class="nb">美容ビジネス</span><span class="nb">（__GENRE_COUNT__ジャンル）</span></span></h1>
  </header>

  <div class="controls">
    <form class="row search-row" id="search" role="search">
      <div class="search-box">
        <input type="search" id="q" autocomplete="off"
               enterkeyhint="search" aria-label="検索ワード"
               role="combobox" aria-autocomplete="list"
               aria-controls="genre-suggest" aria-expanded="false"
               placeholder="調べたいワード（例: ネイルサロン）">
        <ul class="suggest" id="genre-suggest" role="listbox" aria-label="収集ジャンル" hidden></ul>
      </div>
      <button type="submit" class="search-btn">検索</button>
    </form>
    <p class="hint" id="hint"></p>
    <div class="row sort-row">
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
    </div>
  </div>

  <div class="count" id="count"></div>
  <div id="list"></div>
</div>

<script id="data" type="application/json">__DATA__</script>
<script id="genre-list" type="application/json">__GENRES__</script>
<script>
(function () {
  var readJSON = function (id) { return JSON.parse(document.getElementById(id).textContent); };
  var POSTS = readJSON('data');
  var GENRES = readJSON('genre-list');
  var RISING = __RISING__;   // 伸び率の上位10%にあたる値

  var els = {
    sort: document.getElementById('sort'),
    period: document.getElementById('period'),
    q: document.getElementById('q'),
    search: document.getElementById('search'),
    suggest: document.getElementById('genre-suggest'),
    hint: document.getElementById('hint'),
    list: document.getElementById('list'),
    count: document.getElementById('count')
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

  // --- 検索 ---
  // ジャンルのタブは置かない。調べたい語を打つと、その語で伸びている投稿が出る。
  //
  // 語の比べ方:
  //   - 全角/半角と英字の大小はそろえる（「ＡＧＡ」でも「aga」でも当たる）
  //   - 空白で区切った語はすべて含むもの（AND）。「マツエク 集客」で両方を含む投稿
  //   - ジャンル名と同じ語は「そのジャンルで集めた投稿」＋「本文にその語を含む投稿」。
  //     ジャンルの投稿は収集時に関連度フィルタを通っているので、本文に語そのものが
  //     無くても話題は合っている（「マツエク」で集めて本文は「まつげ」だけ、など）
  //   - ジャンル名はひらがな・カタカナの違いも吸収する（「しみ」でジャンル「シミ」）。
  //     ただし本文はジャンル名の表記で探す。「しみ」のまま本文を探すと
  //     「楽しみ」「しみじみ」が大量に当たるため
  function norm(t) {
    t = String(t || '');
    if (t.normalize) t = t.normalize('NFKC');
    return t.toLowerCase();
  }
  // ひらがなをカタカナに寄せる。ジャンル名との突き合わせにだけ使う
  function kana(t) {
    return norm(t).replace(/[ぁ-ゖ]/g, function (c) {
      return String.fromCharCode(c.charCodeAt(0) + 0x60);
    });
  }

  var GENRE_BY_KANA = {};
  GENRES.forEach(function (g) { GENRE_BY_KANA[kana(g)] = g; });

  // 検索語を、判定に使う形へ一度だけ組み立てる
  //
  // 「ネイルサロン」「ネイル×サロン」は「ネイル」と「サロン」の掛け合わせとして読む。
  // 1語のまま本文を探すと「ネイルサロン」と続けて書いた投稿しか当たらず、
  // ネイルで集めた投稿のうちサロンの話をしているものが漏れるため。
  // 前半がジャンル名のときだけ分ける（「エステサロン」はそのまま本文を探す）
  var SALON = 'サロン';
  // 語の区切り。空白のほかに「×」「✕」「✖️」も区切りとして扱う
  var SEP = /[\s×✕✖️]+/;

  function parseQuery(raw) {
    var terms = [];
    norm(raw).split(SEP).filter(Boolean).forEach(function (w) {
      var k = kana(w);
      var genre = GENRE_BY_KANA[k] || null;
      if (!genre && k.length > SALON.length && k.slice(-SALON.length) === SALON) {
        var head = GENRE_BY_KANA[k.slice(0, -SALON.length)] || null;
        if (head) {
          terms.push({ word: norm(head), genre: head });
          terms.push({ word: norm(SALON), genre: null });
          return;
        }
      }
      terms.push({ word: genre ? norm(genre) : w, genre: genre });
    });
    return terms;
  }

  function matches(p, terms) {
    if (!terms.length) return true;
    if (p._hay === undefined) p._hay = norm(p.text + ' ' + p.username);
    return terms.every(function (t) {
      if (t.genre && p.genres.indexOf(t.genre) !== -1) return true;
      return p._hay.indexOf(t.word) !== -1;
    });
  }

  // --- 入力候補 ---
  // タブの代わりに、検索窓をタップしたとき収集ジャンルを一覧で見せる。
  // <datalist> は iPhone の Safari などで一覧が出ないので自前で組む。
  // 候補は打ちかけの最後の語で絞る（ひらがなでも当たる）。選ぶとその語に置き換える
  // 各ジャンルのすぐ後ろに「◯◯サロン」も置く。こちらは何か打ちかけたときだけ出す
  // （空欄で全部出すと候補が倍の長さになり、目当てのジャンルを探しにくい）
  var suggestItems = [];
  function addSuggest(label, id, combo) {
    var li = mk('li', 'suggest-item' + (combo ? ' combo' : ''), label);
    li.setAttribute('role', 'option');
    li.id = id;
    li.dataset.genre = label;
    li.dataset.key = kana(label);
    if (combo) li.dataset.combo = '1';
    els.suggest.appendChild(li);
    suggestItems.push(li);
  }
  GENRES.forEach(function (g, i) {
    addSuggest(g, 'suggest-' + i, false);
    // 「美容サロン」に「サロン」を重ねない
    if (kana(g).slice(-SALON.length) !== SALON) addSuggest(g + SALON, 'suggest-s' + i, true);
  });
  var activeIndex = -1;

  // 打ちかけの最後の語。「ネイル×サ」の「サ」のように、× の後ろも1語として見る
  function lastWord(v) {
    var m = String(v).match(/(^|[\s×✕✖️])([^\s×✕✖️]*)$/);
    return m ? m[2] : '';
  }

  function visibleItems() {
    return suggestItems.filter(function (li) { return !li.hidden; });
  }

  function setActive(i) {
    var items = visibleItems();
    suggestItems.forEach(function (li) { li.classList.remove('active'); li.removeAttribute('aria-selected'); });
    activeIndex = items.length ? Math.max(-1, Math.min(i, items.length - 1)) : -1;
    if (activeIndex >= 0) {
      var li = items[activeIndex];
      li.classList.add('active');
      li.setAttribute('aria-selected', 'true');
      els.q.setAttribute('aria-activedescendant', li.id);
      if (li.scrollIntoView) li.scrollIntoView({ block: 'nearest' });
    } else {
      els.q.removeAttribute('aria-activedescendant');
    }
  }

  function openSuggest() {
    var key = kana(lastWord(els.q.value));
    var shown = 0;
    suggestItems.forEach(function (li) {
      var hit = key ? li.dataset.key.indexOf(key) !== -1 : !li.dataset.combo;
      li.hidden = !hit;
      if (hit) shown++;
    });
    els.suggest.hidden = shown === 0;
    els.q.setAttribute('aria-expanded', shown ? 'true' : 'false');
    setActive(-1);
  }

  function closeSuggest() {
    els.suggest.hidden = true;
    els.q.setAttribute('aria-expanded', 'false');
    setActive(-1);
  }

  // 選んだジャンルで、打ちかけの最後の語を置き換えて検索する。
  // スマホではキーボードを閉じて結果を見せる
  function pickGenre(g) {
    var v = els.q.value;
    var rest = v.slice(0, v.length - lastWord(v).length);
    els.q.value = rest + g;
    closeSuggest();
    render();
    writeUrlQuery();
    els.q.blur();
  }

  // タップした瞬間に検索窓からフォーカスが外れると、先に一覧が閉じて
  // 選べなくなる。押した時点ではフォーカスを動かさない
  els.suggest.addEventListener('mousedown', function (e) { e.preventDefault(); });
  els.suggest.addEventListener('click', function (e) {
    var li = e.target.closest ? e.target.closest('.suggest-item') : null;
    if (li) pickGenre(li.dataset.genre);
  });

  // 検索欄の下の一言。自前の文言なので文節ごとに .nb で囲う
  function renderHint(terms) {
    els.hint.textContent = '';
    if (!terms.length) {
      phrases(els.hint, ['空欄のときは', '全ジャンルの', '伸びている投稿を', '表示します。',
                         '複数の語は', '空白で区切ると', 'すべて含む投稿に', '絞れます。']);
      return;
    }
    var named = terms.filter(function (t) { return t.genre; })
                     .map(function (t) { return '「' + t.genre + '」'; });
    var plain = terms.filter(function (t) { return !t.genre; })
                     .map(function (t) { return '「' + t.word + '」'; });
    if (named.length && plain.length) {
      // 「ネイルサロン」＝ネイルで集めた投稿のうち、サロンも含むもの
      phrases(els.hint, [named.join(''), 'で集めた投稿と、', '本文に語を含む投稿のうち、',
                         plain.join('') + 'も', '含むものを', '出しています。']);
    } else if (named.length) {
      phrases(els.hint, [named.join(''), 'は収集ジャンルです。', 'そのジャンルで集めた投稿と、',
                         '本文に語を含む投稿を', '出しています。']);
    } else {
      phrases(els.hint, ['本文と', 'ユーザー名から', '探しています。']);
    }
  }

  // URL の ?q= で開くと、その語で検索した状態から始まる。
  // よく見る語をブックマークしておけるように
  function readUrlQuery() {
    try {
      var v = new URLSearchParams(window.location.search).get('q');
      if (v) els.q.value = v;
    } catch (e) { /* 読めなければ空欄のまま始める */ }
  }
  function writeUrlQuery() {
    try {
      var url = new URL(window.location.href);
      var v = els.q.value.trim();
      if (v) url.searchParams.set('q', v); else url.searchParams.delete('q');
      window.history.replaceState(null, '', url.toString());
    } catch (e) { /* file:// などで書けなくても検索は続ける */ }
  }

  function fmtAge(h) {
    if (h === null || h === undefined) return '不明';
    if (h < 24) return Math.round(h) + '時間前';
    return Math.round(h / 24) + '日前';
  }

  function filtered(terms) {
    var days = parseInt(els.period.value, 10);

    return POSTS.filter(function (p) {
      if (days > 0) {
        if (p.ageHours === null || p.ageHours > days * 24) return false;
      }
      return matches(p, terms);
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
    var terms = parseQuery(els.q.value);
    renderHint(terms);
    var rows = sorted(filtered(terms));
    els.count.textContent = rows.length + ' 件を表示';
    els.list.textContent = '';

    if (rows.length === 0) {
      // 「別の語で」を1かたまりにして、「で」が行頭に来ないようにする
      els.list.appendChild(phrases(mk('div', 'empty'), [
        '該当する投稿が', 'ありません。', '別の語で', '検索するか、', '期間を', '広げてください。'
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
      // どのジャンルの収集で見つかったかを出す。
      // 検索語そのものを出すと、「オンライン秘書」と「オンライン秘書 経営」が
      // 並んで冗長になり、1ジャンル1語のときは同じ語が二重に出る
      var seenTags = {};
      p.genres.forEach(function (t) {
        if (seenTags[t]) return;
        seenTags[t] = true;
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

  [els.sort, els.period].forEach(function (el) {
    el.addEventListener('change', render);
  });
  // 打つそばから絞り込む。3000件なら入力のたびに描き直しても引っかからない
  els.q.addEventListener('input', function () { render(); writeUrlQuery(); openSuggest(); });
  els.q.addEventListener('focus', openSuggest);
  // アプリ内ブラウザでは、すでにフォーカスがある検索窓をもう一度タップしても
  // focus が来ない（キーボードだけ閉じて開き直す）ことがある。タップでも開く
  els.q.addEventListener('click', function () { if (els.suggest.hidden) openSuggest(); });
  // 一覧の外をタップしたら閉じる
  els.q.addEventListener('blur', closeSuggest);
  // PC では矢印キーで候補を選び、Enter で決める。Esc で閉じる
  els.q.addEventListener('keydown', function (e) {
    if (e.isComposing || composing) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (els.suggest.hidden) openSuggest();
      e.preventDefault();
      setActive(activeIndex + (e.key === 'ArrowDown' ? 1 : -1));
    } else if (e.key === 'Enter' && activeIndex >= 0 && !els.suggest.hidden) {
      e.preventDefault();
      pickGenre(visibleItems()[activeIndex].dataset.genre);
    } else if (e.key === 'Escape') {
      closeSuggest();
    }
  });
  // 日本語入力の変換を確定する Enter で、検索が走ってキーボードが閉じないようにする。
  // isComposing だけでは Safari で確定直後の Enter を取りこぼすので、
  // compositionend の直後も1拍だけ「変換中」とみなす
  var composing = false;
  els.q.addEventListener('compositionstart', function () { composing = true; });
  els.q.addEventListener('compositionend', function () {
    setTimeout(function () { composing = false; }, 0);
  });
  // Enter や「検索」ボタンでページが再読み込みされないようにする。
  // スマホではキーボードを閉じて結果を見せる
  els.search.addEventListener('submit', function (e) {
    e.preventDefault();
    if (composing) return;
    closeSuggest();
    render();
    writeUrlQuery();
    els.q.blur();
  });

  readUrlQuery();
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
    html = render_html(rows, config_genres)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")

    # 設定に無いジャンルが混ざっていたら、生成した時点で気づけるようにする
    if config_genres:
        stale = sorted({g for r in rows for g in r["genres"]} - set(config_genres))
        if stale:
            print("[注意] 設定に無いジャンル名がページに載っています: " + " / ".join(stale))
            print("       python3 scripts/rename_genre.py '<古い名前>' '<新しい名前>'")

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
