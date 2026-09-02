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
check('「絞り込みを」が1かたまりになっている', emptyUnits.includes('絞り込みを'), emptyUnits);
check('全文が .nb の中に収まっている',
      emptyUnits.join('') === empty.textContent, { units: emptyUnits.join(''), all: empty.textContent });

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

console.log('--- 6. ジャンル別の横棒 ---');
// 名前の長さで列幅が動くと、棒の開始位置が行ごとにずれる
check('名前の列が固定幅',
      /\.bar-row\s*\{[^}]*grid-template-columns:\s*[\d.]+em 1fr auto/s.test(css), null);
const barUnits = [...doc.querySelectorAll('.bar-name .nb')].map(e => e.textContent);
check('ジャンル名が文節ごとに分かれている', barUnits.length > 0, barUnits);
check('「・」が行頭に来ない', barUnits.every(u => !u.startsWith('・')), barUnits);
check('棒グラフに助詞始まりが無い',
      barUnits.filter(t => PARTICLES.some(pt => t.startsWith(pt))).length === 0, barUnits);

console.log('--- 7. ジャンルのチップ ---');
// 「ダイエット・痩身」のような長いジャンル名が「ダイ」「エット」に割れないこと
check('ジャンル名が途中で割れない',
      /\.chip-name\s*\{[^}]*white-space:\s*nowrap/s.test(css), null);
// 「収集待ち」が等幅フォントに落ちて崩れないこと
check('収集待ちの表記が本文と同じ書体',
      /\.bar-row\.pending\s+\.bar-count\s*\{[^}]*font-family/s.test(css), null);
const chipNames = [...doc.querySelectorAll('.chip-name')].map(e => e.textContent.trim());
check('チップに助詞始まりが無い',
      chipNames.filter(t => PARTICLES.some(pt => t.startsWith(pt))).length === 0, chipNames);

console.log(`\n結果: ${pass} pass / ${fail} fail`);
process.exit(fail === 0 ? 0 : 1);
