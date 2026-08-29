# Threads 伸びてる投稿コレクター

薄毛 / 育毛 / フェイシャル 領域で伸びている Threads 投稿を集め、HTML 一覧にする。
収集専用で、分析も文章生成もしない。LLM を使わないので API 課金は発生しない。

> コマンドは1行ずつコピーして実行する。zsh は対話シェルだと `#` をコメントとして
> 扱わないので、`#` で始まる説明文を一緒に貼り付けるとエラーになる。

## 仕組み

Threads の公式 API は使っていない。公式 API には `like_count` というフィールドが
存在せず、他人の公開投稿も App Review を通すまで検索できないため、「いいね順」を
作れないことが確認済みだから（2026-08 時点）。

代わりに Playwright でブラウザから Threads の検索結果を開き、**画面の DOM ではなく
Threads のフロントエンド自身が受け取っている JSON レスポンスを傍受**して投稿を拾う。
クラス名は難読化されていて頻繁に変わるが、JSON の中身の方が構造が安定しているため。

## 準備（初回のみ）

```bash
npm install --prefix . playwright
```

続いて Threads にログインする。ブラウザが開くのでログインし、終わったら閉じる。
セッションは `.browser-profile/` に保存され、以後は自動で使われる。

```bash
python3 scripts/collect.py --login
```

## 使い方

1. 試運転（3キーワードだけ、ブラウザを表示して動きを確認する）

```bash
python3 scripts/collect.py --limit 3 --headful
```

2. 本番の収集

```bash
python3 scripts/collect.py
```

3. HTML を作って開く

```bash
python3 scripts/build_html.py
open docs/index.html
```

収集は繰り返し実行してよい。投稿 ID で重複排除され、いいね数は毎回最新に更新される。

### よく使うオプション

| コマンド | 意味 |
|---|---|
| `python3 scripts/collect.py --genre フェイシャル` | ジャンルを絞る |
| `python3 scripts/collect.py --limit 3` | 先頭3キーワードだけ（試運転） |
| `python3 scripts/collect.py --headful` | ブラウザを表示して動きを見る |
| `python3 scripts/collect.py --delay 10` | キーワード間の待機を10秒にする |
| `python3 scripts/collect.py --dry-run` | 保存せず件数だけ見る |
| `python3 scripts/collect.py --dump-dir data/dump` | 生レスポンスを保存（原因調査用） |
| `python3 scripts/collect.py --no-filter` | 関連度フィルタを外して全部保存する |
| `python3 scripts/collect.py --min-posts 10` | 取得件数がこれ未満ならやり直す（既定5） |

## 公開して自動更新する

`docs/index.html` を GitHub Pages で配信し、1日3回自動で更新する。

まず GitHub 側を用意する（初回のみ）。

```bash
gh auth login
```

```bash
bash scripts/setup_github.sh
```

公開リポジトリを作り、`main` ブランチの `/docs` を Pages として有効にして、
URL を表示する。ページには `noindex` を入れてあるので検索結果には出ないが、
**URL を知っていれば誰でも見られる**点は理解しておくこと。

次に自動実行を登録する。

```bash
bash scripts/install_launchd.sh
```

朝7時 / 昼13時 / 夜21時 に、収集 → HTML生成 → push まで自動で走る。
URL は変わらず中身だけが更新される。解除は `bash scripts/uninstall_launchd.sh`、
ログは `logs/collect.log`。

Threads へのアクセスが起きるのは**この3回だけ**。ページを誰が何回開いても、
Threads へのリクエストは増えない。

Mac がスリープしていると実行されない。常に動かしたいときは自動起床を設定する。

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00
```

### 手動で公開だけしたいとき

```bash
bash scripts/publish.sh
```

変化が無ければ何もしない。リモート未設定なら黙ってスキップするので、
ローカル運用のままでも壊れない。

## 検索キーワードと関連度フィルタ

`config/keywords.json` を編集する。ジャンルを増やしても収集・表示ともに追従する。
キーワードを増やすほどアクセス回数が増えるので、1ジャンル5〜8個を目安にする。

```json
{
  "genres": {
    "薄毛": {
      "keywords": ["薄毛 対策", "つむじ 薄毛"],
      "required_any": ["髪", "毛", "薄毛", "頭皮"]
    }
  }
}
```

`required_any` は関連度フィルタ。**本文にこのうち1語も含まない投稿は保存しない。**

Threads の検索は語の一致が緩く、たとえば `つむじ 薄い` で検索すると妊娠検査薬の
「薄いけど確実に濃くなってる」やアイメイクの「一重でも二重でも」が混ざる。実測では
58件中7件が無関係だった。`required_any` はそれを落とすための関門で、除外した件数と
中身は実行時に必ず表示される（黙って捨てない）。

一時的に外したいときは `--no-filter` を付ける。

## 蓄積とページに載せる範囲

収集は繰り返すたびに積み上がる。投稿 ID で重複排除され、いいね数だけが最新に
更新される。消えることはない。

そのまま全部ページに載せると HTML が際限なく太る。1件あたり約700バイトなので、
ワーストケース（1日3回 × 16キーワード × 31件がすべて新規）では **1日1MB** 増え、
**約100日で GitHub の1ファイル上限100MB に当たって更新が止まる**。その前に、
数万枚のカードを積んだページはブラウザで開けなくなる。

そこで分けている。

| | 内容 | 増え方 |
|---|---|---|
| `data/posts.json` | **全履歴**。1件も捨てない | 際限なく増えるが Git 管理外なのでリポジトリは太らない |
| `docs/index.html` | 直近180日 かつ 最大1500件 | 常に約1MBで頭打ち |

範囲は変えられる。

```bash
python3 scripts/build_html.py --max-age-days 90 --max-posts 800
```

どちらも `0` で無制限になる。載せなかった件数と理由は実行のたびに表示され、
ページ上部にも「蓄積 N 件のうち M 件を表示」と出る。黙って捨てることはない。

### 件数を絞るときの選び方

いいね順だけで上位を残すと、**新しくて急上昇中だがまだ総いいねが少ない投稿**が
落ちる。逆に伸び順だけだと定番の強い投稿が落ちる。そこで両方の上位を半分ずつ
確保してから、残りをいいね順で埋めている。

## 並び替えの考え方

| 並び | 意味 |
|---|---|
| 時間あたりいいね（既定） | `いいね数 ÷ 経過時間`。今まさに伸びている投稿が上位に来る |
| いいね数 | 絶対値。定番として強い投稿が上位に来る |
| 新着順 | 投稿が新しい順 |

既定を「時間あたりいいね」にしてあるのは、単純ないいね順だと古い定番投稿が上位に
居座り続けて、今刺さっているネタが埋もれるため。

投稿直後の数件でこの値が跳ね上がるのを防ぐため、経過時間は最低6時間として計算する
（`scripts/build_html.py` の `VELOCITY_FLOOR_HOURS`）。

## 構成

```
config/keywords.json        検索キーワード定義
scripts/scrape.mjs          Playwright でブラウザを動かす
scripts/extract.mjs         レスポンスJSONから投稿を抜き出す（純粋関数）
scripts/collect.py          scrape.mjs を呼び、data/posts.json にマージ
scripts/build_html.py       posts.json → docs/index.html
scripts/run_collect.sh      収集→HTML生成→公開まで一息で実行（launchd から呼ばれる）
scripts/publish.sh          docs/index.html を GitHub Pages へ push
scripts/setup_github.sh     GitHub リポジトリと Pages の初期設定
scripts/install_launchd.sh  自動実行の登録
tests/run.sh                回帰テスト
```

収集（`collect.py` + `scrape.mjs`）と表示（`build_html.py`）は `data/posts.json` を
挟んで分離してある。取得方法が変わっても表示側は影響を受けない。

## 件数が安定しない場合

検索結果は通常20件単位で返る。あるキーワードだけ極端に少ないときは、読み込みが
終わる前に次へ進んでしまっている。`scrape.mjs` は固定時間で待つのではなく
**実際に投稿が届くまで待ち**、それでも `--min-posts` 未満なら一度やり直す。

やり直しても増えないときは `--min-posts` を上げるか、`--delay` を長くして
アクセス間隔を空ける。

## 取れなくなったときは

Threads 側の仕様変更で 0 件になることがある。そのときは生レスポンスを保存して中身を見る。

```bash
python3 scripts/collect.py --limit 1 --dump-dir data/dump --headful
```

`data/dump/` に保存された JSON を見て、投稿オブジェクトの形が変わっていれば
`scripts/extract.mjs` の判定条件を直す。

## テスト

```bash
bash tests/run.sh
```

ブラウザも通信も使わずに、抽出ロジック・やり直し判定・マージ処理・HTML 生成・
公開判定を検証する。GitHub には接続せず、ローカルのベアリポジトリを push 先にする。

## 注意

Threads の利用規約は自動アクセスを制限している。アカウントへのリスクはゼロではない。
キーワード間に待機を入れ、実行を1日3回に固定しているのはそのため。
`--delay` を短くしたり実行頻度を上げたりすると、その分リスクが上がる。
