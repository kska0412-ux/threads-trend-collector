/**
 * 蓄積が0件のときにページが壊れないことを検証する。
 *
 * 収集を始める前や、ジャンルを総入れ替えした直後は必ず0件から始まる。
 * ここで伸び率の基準が Python の inf のまま埋まると、JS では未定義の
 * 識別子になってスクリプトが丸ごと止まり、検索も一覧も効かなくなる。
 */
import fs from 'fs';
import { pathToFileURL } from 'url';

const { JSDOM } = await import(
  pathToFileURL(`${process.env.SCRATCH}/node_modules/jsdom/lib/api.js`).href
);

const errors = [];
const dom = new JSDOM(fs.readFileSync(process.env.SCRATCH + '/preview_empty.html', 'utf8'),
                      { runScripts: 'dangerously' });
dom.window.addEventListener('error', e => errors.push(e.message));
const doc = dom.window.document;
const win = dom.window;

let pass = 0, fail = 0;
function check(label, cond, actual) {
  if (cond) { pass++; console.log(`  OK   ${label}`); }
  else { fail++; console.log(`  FAIL ${label}  → 実際: ${JSON.stringify(actual)}`); }
}

console.log('--- スクリプトが動くこと ---');
check('JSエラーが出ない', errors.length === 0, errors);
const rising = win.eval('typeof RISING');
check('伸び率の基準がJSの値になっている（infではない）',
      /Infinity|\d/.test(String(win.document.documentElement.innerHTML.match(/var RISING = ([^;]+);/)[1])),
      String(win.document.documentElement.innerHTML.match(/var RISING = ([^;]+);/)[1]));

console.log('--- 0件でも骨組みは出ること ---');
const declared = Number((doc.querySelector('.ver').textContent.match(/(\d+)ジャンル/) || [])[1]);
check('見出しがジャンル数を名乗る', declared > 0, doc.querySelector('.ver').textContent);
// 0件でも何を探せるかが分からないと、対象が無いツールに見えてしまう
const suggest = doc.querySelectorAll('#genre-suggest option');
check('入力候補に設定のジャンルが並ぶ', suggest.length === declared, { suggest: suggest.length, declared });
check('検索窓が出る', doc.getElementById('q') !== null, null);
check('チップも棒も出さない',
      doc.querySelectorAll('.chip').length === 0 && doc.querySelectorAll('.bar-row').length === 0, null);

console.log('--- 0件の一覧 ---');
check('カードは0件', doc.querySelectorAll('.card').length === 0, doc.querySelectorAll('.card').length);
check('件数表示が出る', doc.getElementById('count').textContent === '0 件を表示',
      doc.getElementById('count').textContent);
check('空状態のメッセージが出る', doc.querySelector('.empty') !== null,
      doc.getElementById('list').innerHTML.slice(0, 60));

console.log('--- 0件でも操作が壊れないこと ---');
const q = doc.getElementById('q');
q.value = 'なにか';
q.dispatchEvent(new win.Event('input', { bubbles: true }));
check('検索しても落ちない', errors.length === 0, errors);
const sortEl = doc.getElementById('sort');
sortEl.value = 'likes';
sortEl.dispatchEvent(new win.Event('change', { bubbles: true }));
check('並び替えても落ちない', errors.length === 0, errors);
const form = doc.getElementById('search');
form.dispatchEvent(new win.Event('submit', { bubbles: true, cancelable: true }));
check('検索ボタンを押しても落ちない', errors.length === 0, errors);
q.value = '育毛';
q.dispatchEvent(new win.Event('input', { bubbles: true }));
check('ジャンル語で探しても落ちない', errors.length === 0, errors);

console.log(`\n結果: ${pass} pass / ${fail} fail`);
process.exit(fail === 0 ? 0 : 1);
