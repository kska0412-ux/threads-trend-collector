/**
 * 改行の作法を検証する。
 *
 * 守りたいこと:
 *   1. 単語の途中で改行しない（「デザイン」を「デ」で割らない）
 *   2. 「を」「と」などの助詞が行頭に来ない
 *
 * 1 は CSS の word-break で決まる。break-word / break-all は途中で割るので使わない。
 * 2 は CSS では防げないため、自前の文言を文節ごとに nowrap で囲って担保する。
 *   （収集した投稿の本文は他人の文章なので、ここでは対象外）
 */
import fs from 'fs';
import { pathToFileURL } from 'url';

const { JSDOM } = await import(
  pathToFileURL(`${process.env.SCRATCH}/node_modules/jsdom/lib/api.js`).href
);

const html = fs.readFileSync(process.env.SCRATCH + '/preview.html', 'utf8');
const dom = new JSDOM(html, { runScripts: 'dangerously' });
const doc = dom.window.document;
const cssRaw = doc.querySelector('style').textContent;
// コメント内の説明文に反応しないよう、実際の指定だけを見る
const css = cssRaw.replace(/\/\*[\s\S]*?\*\//g, '');

let pass = 0, fail = 0;
function check(label, cond, actual) {
  if (cond) { pass++; console.log(`  OK   ${label}`); }
  else { fail++; console.log(`  FAIL ${label}  → 実際: ${JSON.stringify(actual)}`); }
}

console.log('--- 1. 単語の途中で改行しない ---');
const badBreaks = css.match(/word-break:\s*(break-word|break-all)/g);
check('word-break に break-word / break-all を使っていない', badBreaks === null, badBreaks);
check('word-break: normal を指定している', /word-break:\s*normal/.test(css), null);
check('あふれる時だけ折る overflow-wrap を使っている', /overflow-wrap:\s*break-word/.test(css), null);
check('日本語の禁則を強める line-break: strict がある', /line-break:\s*strict/.test(css), null);
check('本文にも適用されている', /\.text\s*\{[^}]*word-break:\s*normal/s.test(css), null);

console.log('--- 2. 文節をまとめる仕組み ---');
check('.nb が nowrap で定義されている', /\.nb\s*\{\s*white-space:\s*nowrap/.test(css), null);

console.log('--- 3. 助詞が行頭に来ないこと（自前の文言） ---');
// 該当なしのメッセージ
const q = doc.getElementById('q');
q.value = 'ぜったいに存在しない語';
q.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
const empty = doc.querySelector('.empty');
check('該当なしのメッセージが出る', empty !== null, null);
const emptyUnits = [...empty.querySelectorAll('.nb')].map(e => e.textContent);
check('文節ごとに分かれている', emptyUnits.length >= 2, emptyUnits);
check('「別の語で」が1かたまりになっている', emptyUnits.includes('別の語で'), emptyUnits);
check('全文が .nb の中に収まっている',
      emptyUnits.join('') === empty.textContent, { units: emptyUnits.join(''), all: empty.textContent });

// 検索欄の下のヒント。空欄のときと、ジャンル語で探したときの両方
q.value = '';
q.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
const hint = doc.getElementById('hint');
const hintBlank = [...hint.querySelectorAll('.nb')].map(e => e.textContent);
check('空欄のヒントが文節ごとに分かれている', hintBlank.length >= 2, hintBlank);
check('空欄のヒントが全文 .nb に収まる', hintBlank.join('') === hint.textContent,
      { units: hintBlank.join(''), all: hint.textContent });
q.value = '育毛';
q.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
const hintGenre = [...hint.querySelectorAll('.nb')].map(e => e.textContent);
check('ジャンル語のヒントが全文 .nb に収まる', hintGenre.join('') === hint.textContent,
      { units: hintGenre.join(''), all: hint.textContent });
check('ヒントの括弧が行末・行頭で割れない',
      hintBlank.concat(hintGenre).every(u => !/[（(「『]$/.test(u) && !/^[）)」』、。\s]/.test(u)),
      hintBlank.concat(hintGenre));
q.value = 'ぜったいに存在しない語';
q.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
q.value = '頭皮';
q.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
const hintText = [...hint.querySelectorAll('.nb')].map(e => e.textContent);
check('本文検索のヒントが全文 .nb に収まる', hintText.join('') === hint.textContent,
      { units: hintText.join(''), all: hint.textContent });

// 助詞で始まるかたまりが無いこと
const PARTICLES = ['を', 'と', 'は', 'が', 'に', 'で', 'の', 'も', 'へ', 'や', 'から', 'まで'];
const allUnits = [...doc.querySelectorAll('.nb')].map(e => e.textContent.trim()).filter(Boolean);
const startsWithParticle = allUnits.filter(t => PARTICLES.some(p => t.startsWith(p)));
check('助詞で始まるかたまりが無い', startsWithParticle.length === 0, startsWithParticle);

console.log('--- 4. 数値と単位、短いラベル ---');
check('数値と単位が離れない', /\.stat-value\s*\{[^}]*white-space:\s*nowrap/s.test(css), null);
check('集計ラベルが途中で割れない', /\.stat-label\s*\{[^}]*white-space:\s*nowrap/s.test(css), null);
check('件数表示が途中で割れない', /\.count\s*\{[^}]*white-space:\s*nowrap/s.test(css), null);
check('タグが途中で割れない', /\.tag\s*\{[^}]*white-space:\s*nowrap/s.test(css), null);
check('伸び中バッジが途中で割れない', /\.badge\s*\{[^}]*white-space:\s*nowrap/s.test(css), null);
check('元投稿リンクが途中で割れない', /\.link\s*\{[^}]*white-space:\s*nowrap/s.test(css), null);

console.log('--- 5. 見出しの但し書き ---');
const ver = doc.querySelector('.ver');
const verUnits = [...ver.querySelectorAll('.nb')].map(e => e.textContent);
check('文節ごとに分かれている', verUnits.length === 2, verUnits);
check('全文が .nb の中に収まっている',
      verUnits.join('') === ver.textContent, { units: verUnits.join(''), all: ver.textContent });
// 行末に開き括弧を残さない／閉じ括弧と句読点を行頭に置かない
check('括弧が行末・行頭で割れない',
      verUnits.every(u => !/[（(「『]$/.test(u) && !/^[）)」』、。\s]/.test(u)), verUnits);
check('ジャンル数と単位が離れない', verUnits.some(u => /\d+ジャンル/.test(u)), verUnits);

console.log('--- 6. 検索ボタン ---');
check('「検索」ボタンが途中で割れない', /\.search-btn\s*\{[^}]*white-space:\s*nowrap/s.test(css), null);

console.log(`\n結果: ${pass} pass / ${fail} fail`);
process.exit(fail === 0 ? 0 : 1);
