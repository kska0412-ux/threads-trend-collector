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

from common import BASE_DIR, DATA_FILE, JST, now_jst_iso, parse_timestamp  # noqa: E402

# GitHub Pages は main ブランチの /docs をそのまま配信できるので、ここに出す
OUTPUT_FILE = BASE_DIR / "docs" / "index.html"

# 投稿直後の数件で velocity が跳ね上がるのを防ぐための下限（時間）
VELOCITY_FLOOR_HOURS = 6.0


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


def build_summary(rows, store):
    """一覧の上に出す集計。詳細より先に全体像が分かるようにする。"""
    genres = {}
    for r in rows:
        for g in r["genres"]:
            genres[g] = genres.get(g, 0) + 1
    week = [r for r in rows if r["ageHours"] is not None and r["ageHours"] <= 168]
    return {
        "total": len(rows),
        "genres": sorted(genres.items(), key=lambda kv: -kv[1]),
        "over1000": len([r for r in rows if r["likes"] >= 1000]),
        "thisWeek": len(week),
        "authors": len({r["username"] for r in rows}),
        "updatedAt": (store.get("updated_at") or "")[:16].replace("T", " "),
    }


def render_html(rows, generated_at, store):
    genres = sorted({g for r in rows for g in r["genres"]})
    keywords = sorted({k for r in rows for k in r["keywords"]})

    return (
        TEMPLATE.replace("__DATA__", embed_json(rows))
        .replace("__GENRES__", embed_json(genres))
        .replace("__KEYWORDS__", embed_json(keywords))
        .replace("__SUMMARY__", embed_json(build_summary(rows, store)))
        .replace("__RISING__", str(round(rising_threshold(rows), 4)))
        .replace("__GENERATED__", generated_at)
        .replace("__COUNT__", str(len(rows)))
    )


TEMPLATE = r"""
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- 公開リポジトリで配信するため、検索結果には出さない -->
<meta name="robots" content="noindex, nofollow">
<title>薄毛・育毛・フェイシャルの伸びてる投稿</title>
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
  }

  .wrap { max-width: 880px; margin: 0 auto; padding: 40px 20px 96px; }

  :focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
    border-radius: 4px;
  }

  /* --- 見出し --- */
  .eyebrow {
    font-family: "Roboto Mono", ui-monospace, monospace;
    font-size: .68rem;
    letter-spacing: .18em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 10px;
  }
  h1 {
    font-family: "Zen Old Mincho", "Hiragino Mincho ProN", "Yu Mincho", serif;
    font-weight: 900;
    font-size: clamp(1.5rem, 4vw, 2.1rem);
    line-height: 1.35;
    letter-spacing: .01em;
    margin: 0 0 10px;
    text-wrap: balance;
  }
  .lede { color: var(--muted); font-size: .88rem; margin: 0; }

  /* --- 集計サマリ：詳細より先に全体像を出す --- */
  .summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    margin: 28px 0 8px;
  }
  .stat { background: var(--surface); padding: 14px 16px; }
  .stat-label {
    font-size: .7rem; color: var(--muted); letter-spacing: .06em;
    display: block; margin-bottom: 4px;
  }
  .stat-value {
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
  .count {
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
    white-space: pre-wrap; word-break: break-word;
    font-size: .92rem; margin: 0 0 12px;
  }

  .tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .tag {
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
    <p class="eyebrow">Threads Trend Collector</p>
    <h1>薄毛・育毛・フェイシャルの伸びてる投稿</h1>
    <p class="lede">いま反応が集まっている投稿を集めた一覧です。投稿ネタを探すために使います。</p>
  </header>

  <div class="summary" id="summary"></div>
  <p class="stamp">最終収集 __GENERATED__</p>

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
    summary: document.getElementById('summary')
  };

  function mk(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  // --- 集計サマリ ---
  (function renderSummary() {
    var tiles = [
      ['蓄積した投稿', SUMMARY.total, '件'],
      ['直近7日の投稿', SUMMARY.thisWeek, '件'],
      ['1000いいね超え', SUMMARY.over1000, '件'],
      ['投稿者', SUMMARY.authors, '人']
    ];
    SUMMARY.genres.forEach(function (pair) { tiles.push([pair[0], pair[1], '件']); });

    tiles.forEach(function (t) {
      var box = mk('div', 'stat');
      box.appendChild(mk('span', 'stat-label', t[0]));
      var v = mk('div', 'stat-value', String(t[1]));
      v.appendChild(mk('span', 'unit', t[2]));
      box.appendChild(v);
      els.summary.appendChild(box);
    });
  })();

  KEYWORDS.forEach(function (k) {
    var o = document.createElement('option');
    o.value = k; o.textContent = 'キーワード: ' + k;
    els.keyword.appendChild(o);
  });

  GENRES.forEach(function (g) {
    var b = mk('span', 'chip', g);
    b.tabIndex = 0;
    var toggle = function () {
      if (activeGenres.has(g)) { activeGenres.delete(g); b.classList.remove('on'); }
      else { activeGenres.add(g); b.classList.add('on'); }
      render();
    };
    b.addEventListener('click', toggle);
    b.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
    els.genres.appendChild(b);
  });

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
      els.list.appendChild(mk('div', 'empty',
        '条件に合う投稿がありません。絞り込みを緩めてください。'));
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
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[NG] データがありません: {args.input}")
        print("     先に python3 scripts/collect.py を実行してください。")
        return 1

    store = json.loads(args.input.read_text(encoding="utf-8"))
    rows = build_rows(store)
    html = render_html(rows, now_jst_iso()[:16].replace("T", " "), store)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")

    print(f"生成しました: {args.output}  （{len(rows)} 件）")
    print(f"開く: open {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
