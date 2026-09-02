import fs from 'fs';
import { pathToFileURL } from 'url';

const { JSDOM } = await import(
  pathToFileURL(`${process.env.SCRATCH}/node_modules/jsdom/lib/api.js`).href
);

const html = fs.readFileSync(process.env.SCRATCH + '/preview.html', 'utf8');
const errors = [];
const dom = new JSDOM(html, { runScripts: 'dangerously', virtualConsole: undefined });
const { window } = dom;
window.addEventListener('error', e => errors.push(e.message));
const doc = window.document;

const users = () => [...doc.querySelectorAll('.card .user')].map(e => e.textContent.replace('@',''));
const n = () => doc.querySelectorAll('.card').length;
const fire = (el, type) => el.dispatchEvent(new window.Event(type, { bubbles: true }));

let pass = 0, fail = 0;
function check(label, cond, actual) {
  if (cond) { pass++; console.log(`  OK   ${label}`); }
  else { fail++; console.log(`  FAIL ${label}  → 実際: ${JSON.stringify(actual)}`); }
}

console.log('--- 1. 初期描画 ---');
check('カード8件', n() === 8, n());
check('件数表示', doc.getElementById('count').textContent === '8 件を表示', doc.getElementById('count').textContent);
check('デフォルトはvelocity順(hair_clinic_jpが1位)', users()[0] === 'hair_clinic_jp', users().slice(0,3));

console.log('--- 2. 並び替え ---');
const sortEl = doc.getElementById('sort');
sortEl.value = 'likes'; fire(sortEl, 'change');
check('いいね順で skin_pro_88(8900)が1位', users()[0] === 'skin_pro_88', users().slice(0,3));
sortEl.value = 'newest'; fire(sortEl, 'change');
check('新着順で face_yoga_ne(1h)が1位', users()[0] === 'face_yoga_ne', users().slice(0,3));
check('timestamp欠損は最後尾', users()[users().length-1] === 'test_edge', users());
sortEl.value = 'velocity'; fire(sortEl, 'change');

console.log('--- 3. 期間フィルタ ---');
const per = doc.getElementById('period');
per.value = '7'; fire(per, 'change');
check('7日以内(168h)で5件', n() === 5, { count: n(), users: users() });
per.value = '30'; fire(per, 'change');
check('30日以内(720h)で7件[700h=29.2日のp8含む]', n() === 7, { count: n(), users: users() });
per.value = '0'; fire(per, 'change');
check('全期間に戻すと8件', n() === 8, n());

console.log('--- 4. ジャンル絞り込み ---');
const chipName = c => c.querySelector('.chip-name').textContent;
const click = c => c.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
const chips = [...doc.querySelectorAll('.chip')];
const pending = chips.filter(c => c.classList.contains('pending'));

// 対象は10ジャンル。ローテーションで今日まだ回っていないジャンルを隠すと、
// 扱う範囲が狭まったように見えてしまう
// ジャンル構成は変わりうるので、数は直書きせず見出しの宣言と突き合わせる。
// フィクスチャは3ジャンルぶんのデータを持つ
const declared = Number((doc.querySelector('.ver').textContent.match(/(\d+)ジャンル/) || [])[1]);
check('見出しがジャンル数を名乗る', declared > 0, doc.querySelector('.ver').textContent);
check('「すべて」＋宣言どおりのジャンルが並ぶ', chips.length === declared + 1,
      { chips: chips.length, declared });
check('先頭が「すべて」', chipName(chips[0]) === 'すべて', chipName(chips[0]));
check('データが無いジャンルも並ぶ', pending.length === declared - 3, pending.map(chipName));
check('データがある3ジャンルは選べる',
      chips.length - 1 - pending.length === 3,
      chips.filter(c => !c.classList.contains('pending')).map(chipName));
check('件数の数字は出さない', doc.querySelector('.chip-n') === null, doc.querySelector('.chip-n'));
check('データがあるジャンルが先に並ぶ',
      chips.slice(1, 4).every(c => !c.classList.contains('pending')),
      chips.slice(1, 4).map(chipName));
check('未収集は押せないことが伝わる',
      pending.every(c => c.getAttribute('aria-disabled') === 'true' && !c.hasAttribute('tabindex')),
      pending.map(c => [chipName(c), c.getAttribute('aria-disabled'), c.getAttribute('tabindex')]));
// 未選択のときは「すべて」が点いている。10ジャンルあると、どれも押していない状態が
// 分かりにくくなるため
check('初期状態は「すべて」が点灯', chips[0].classList.contains('on'), chips[0].className);

// 押しても何も起きないこと。空振りで0件になるのが一番まずい
click(pending[0]);
check('未収集chipを押しても表示は変わらない', n() === 8, { count: n(), chip: chipName(pending[0]) });
check('未収集chipは点灯しない', !pending[0].classList.contains('on'), pending[0].className);

const facial = chips.find(c => chipName(c) === 'エステティシャン');
click(facial);
check('エステティシャンのみ3件', n() === 3, { count: n(), users: users() });
check('chipにonクラス', facial.classList.contains('on'), facial.className);
check('選択中は「すべて」が消灯', !chips[0].classList.contains('on'), chips[0].className);
check('aria-pressedが連動する', facial.getAttribute('aria-pressed') === 'true',
      facial.getAttribute('aria-pressed'));

// 複数ジャンルはOR。押した分だけ増える
const hage = chips.find(c => chipName(c) === '育毛');
click(hage);
check('2ジャンル選ぶとOR（6件）', n() === 6, { count: n(), users: users() });

// 「すべて」で一括解除できる。10ジャンルを押し戻して回らずに済む
click(chips[0]);
check('「すべて」で解除して8件に戻る', n() === 8, n());
check('解除後はジャンルchipが全部消灯',
      chips.slice(1).every(c => !c.classList.contains('on')),
      chips.slice(1).map(c => c.className));
check('解除後は「すべて」が点灯', chips[0].classList.contains('on'), chips[0].className);

// キーボードでも操作できる
facial.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
check('Enterキーでも絞り込める', n() === 3, n());
click(facial);
check('もう一度押すと解除される', n() === 8, n());

console.log('--- 4b. 見出しのジャンル数 ---');
// データにある数ではなく、設定にある数を出す。でないと収集が一周する前は
// 対象が3ジャンルだけに見えてしまう
// データがあるのは3ジャンルだけ。そこを数えると対象が狭まったように見える
const verText = doc.querySelector('.ver').textContent;
check('データの数ではなく設定の数を名乗る', declared > 3, verText);

console.log('--- 5. キーワード絞り込み ---');
const kwEl = doc.getElementById('keyword');
check('キーワードoption数(ユニーク12+すべて=13)', kwEl.options.length === 13, kwEl.options.length);
kwEl.value = 'AGA'; fire(kwEl, 'change');
check('AGAで2件', n() === 2, { count: n(), users: users() });
kwEl.value = ''; fire(kwEl, 'change');

console.log('--- 6. テキスト検索 ---');
const q = doc.getElementById('q');
q.value = '頭皮'; fire(q, 'input');
check('「頭皮」で2件', n() === 2, { count: n(), users: users() });
q.value = 'ざざざ存在しない'; fire(q, 'input');
check('ヒット0で空状態メッセージ', doc.querySelector('.empty') !== null, doc.getElementById('list').innerHTML.slice(0,80));
q.value = ''; fire(q, 'input');

console.log('--- 7. XSS / エスケープ ---');
const edge = [...doc.querySelectorAll('.card')].find(c => c.textContent.includes('test_edge'));
check('scriptタグは実行されずテキストとして表示', edge.querySelector('script') === null && edge.querySelector('.text').textContent.includes('<script>alert(1)</script>'), edge.querySelector('.text').textContent);
check('&や"もそのまま表示', edge.querySelector('.text').textContent.includes('& "引用"'), edge.querySelector('.text').textContent);

console.log('--- 8. リンク ---');
const link = doc.querySelector('.card .link');
check('元投稿リンクがある', link && link.href.startsWith('https://www.threads.net/'), link && link.href);
check('target=_blank + noopener', link.target === '_blank' && link.rel === 'noopener noreferrer', link.rel);

console.log('--- 9. 集計タイル（余りを出さない） ---');
const css9 = doc.querySelector('style').textContent;
const tiles = [...doc.querySelectorAll('#summary .stat')];
check('タイルはちょうど4枚', tiles.length === 4, tiles.length);
const labels = tiles.map(t => t.querySelector('.stat-label').textContent);
check('表示件数のタイルがある', labels.includes('表示中の投稿'), labels);
// ジャンルをタイルに混ぜると枚数が変わり、最後の1枚が取り残される
const genreNames = [...doc.querySelectorAll('.chip-name')].map(e => e.textContent);
check('ジャンルはタイルに混ざっていない',
      !labels.some(l => genreNames.includes(l)), { labels, genreNames });
check('列数が固定（auto-fitではない）',
      /\.summary\s*\{[^}]*grid-template-columns:\s*repeat\(4,\s*1fr\)/s.test(css9), null);
check('4枚は4列で割り切れる', 4 % 4 === 0, null);
check('狭い画面では2列', /\.summary\s*\{\s*grid-template-columns:\s*repeat\(2,\s*1fr\)/.test(css9), null);
check('4枚は2列でも割り切れる', 4 % 2 === 0, null);
const totalTile = tiles.find(t => t.querySelector('.stat-label').textContent === '表示中の投稿');
check('表示件数が8件', totalTile.querySelector('.stat-value').textContent.startsWith('8'), totalTile.textContent);
const stampText = doc.getElementById('stamp').textContent;
check('最終収集の表示がある', stampText.includes('最終収集'), stampText);
// HTMLを作り直しただけで時刻が進むと、更新されていないのに更新されたように見える
const fixtureUpdatedAt = JSON.parse(fs.readFileSync(process.env.SCRATCH + '/fixture_posts.json', 'utf8')).updated_at.slice(0, 16).replace('T', ' ');
check('最終収集は実際の収集時刻（HTML生成時刻ではない）', stampText.includes(fixtureUpdatedAt), { stamp: stampText, expected: fixtureUpdatedAt });
// 8件すべて表示される版では「蓄積N件のうち」は出ないので、絞り込んだ版で確かめる
const trimmedDoc = new JSDOM(fs.readFileSync(process.env.SCRATCH + '/preview_trimmed.html', 'utf8'),
                             { runScripts: 'dangerously' }).window.document;
const trimmedStamp = trimmedDoc.getElementById('stamp').textContent;
check('絞り込んだときは蓄積件数も出る', /蓄積 \d+ 件のうち \d+ 件を表示/.test(trimmedStamp), trimmedStamp);
check('絞り込んだ結果が3件', trimmedDoc.querySelectorAll('.card').length === 3, trimmedDoc.querySelectorAll('.card').length);
check('絞り込んでいない版では蓄積件数を出さない', !stampText.includes('蓄積'), stampText);

console.log('--- 9b. ジャンル別の横棒 ---');
const bars = [...doc.querySelectorAll('.bar-row')];
const barName = b => b.querySelector('.bar-name').textContent;
const pendingBars = bars.filter(b => b.classList.contains('pending'));
check('設定のジャンルぶん棒が並ぶ', bars.length === declared, bars.map(barName));
check('見出しが出る', doc.querySelector('.breakdown-title').textContent === 'ジャンル別', null);
check('未収集の棒はデータのある3ジャンルを除いた数', pendingBars.length === declared - 3, pendingBars.map(barName));
const widths = bars.map(b => parseFloat(b.querySelector('.bar-fill').style.width));
check('最多ジャンルが100%', Math.max(...widths) === 100, widths);
check('棒の長さが件数順に並ぶ', widths.every((w, i) => i === 0 || widths[i - 1] >= w), widths);
check('未収集の棒は長さ0', pendingBars.every(b => parseFloat(b.querySelector('.bar-fill').style.width) === 0),
      pendingBars.map(b => b.querySelector('.bar-fill').style.width));
// 数字は出さない。棒の長さで強弱は足りる
check('件数の数字は出さない',
      bars.filter(b => !b.classList.contains('pending')).every(b => b.querySelector('.bar-count').textContent === ''),
      bars.map(b => b.querySelector('.bar-count').textContent));
check('未収集だけ理由を添える',
      pendingBars.every(b => b.querySelector('.bar-count').textContent === '収集待ち'),
      pendingBars.map(b => b.querySelector('.bar-count').textContent));
// 名前の長さで列幅が変わると、棒の開始位置が行ごとにずれて長さを比べられない
check('名前の列が固定幅',
      /\.bar-row\s*\{[^}]*grid-template-columns:\s*[\d.]+em 1fr auto/s.test(css9), null);
// 画面幅で列幅を変えると、狭い画面だけ折り返し位置が変わってしまう
const barCols = css9.replace(/\/\*[\s\S]*?\*\//g, '').match(/\.bar-row\s*\{[^}]*grid-template-columns/gs) || [];
check('列幅の指定は1か所だけ', barCols.length === 1, barCols);
// 1行の名前と2行の名前が混ざると、行の間隔がばらついて棒を比べにくい
check('全行が同じ高さになる',
      /\.bar-name\s*\{[^}]*min-height:\s*[\d.]+em/s.test(css9), null);
check('折り返した名前が上下中央に来る',
      /\.bar-name\s*\{[^}]*align-content:\s*center/s.test(css9), null);
// 長い名前は「・」の位置だけで折る。カタカナ語の途中では割らない。
// ジャンル名を直に書くと名前を変えるたびに壊れるので、守るべきことだけ見る
const allUnits = bars.map(b => [...b.querySelectorAll('.bar-name .nb')].map(e => e.textContent));
check('ジャンル名が欠けずに .nb へ入っている',
      allUnits.every((u, i) => u.join('') === barName(bars[i])),
      allUnits.map((u, i) => [u.join(''), barName(bars[i])]).filter(([a, b]) => a !== b));
check('「・」が行頭に来ない',
      allUnits.flat().every(u => !u.startsWith('・')),
      allUnits.flat().filter(u => u.startsWith('・')));
check('「・」は前の語にくっつく',
      allUnits.every(u => u.slice(0, -1).every(x => x.endsWith('・'))), allUnits);
check('「・」の無い名前は1かたまり',
      allUnits.every((u, i) => barName(bars[i]).includes('・') || u.length === 1),
      allUnits.map((u, i) => [barName(bars[i]), u.length]));
// 列幅より長い区切りがあると、そこでカタカナ語が割れる。
// 幅はジャンル名から build_html.py が計算して埋めている
const colEm = Number((css9.match(/\.bar-row\s*\{[^}]*grid-template-columns:\s*([\d.]+)em/s) || [])[1]);
check('列幅がページに埋まっている', colEm > 0, colEm);
const tooLong = allUnits.flat().filter(u => u.length > colEm);
check('どの区切りも列幅に収まる（単語が割れない）', tooLong.length === 0,
      { colEm, tooLong: tooLong.map(u => [u, u.length]) });

console.log('--- 10. 伸び中の表示 ---');
const badges = [...doc.querySelectorAll('.badge')];
check('伸び率上位に伸び中が付く', badges.length >= 1, badges.length);
check('全件には付かない', badges.length < n(), { badges: badges.length, cards: n() });
const risingCards = [...doc.querySelectorAll('.card.rising')];
check('伸び中のカードにrisingクラス', risingCards.length === badges.length, { r: risingCards.length, b: badges.length });
sortEl.value = 'velocity'; fire(sortEl, 'change');
check('伸び中は伸び順の先頭に来る', doc.querySelector('.card').classList.contains('rising'), doc.querySelector('.card').className);

console.log('--- 11. JSエラー ---');
check('コンソールエラーなし', errors.length === 0, errors);

console.log(`\n結果: ${pass} pass / ${fail} fail`);
process.exit(fail === 0 ? 0 : 1);
