/**
 * 蓄積が0件のときにページが壊れないことを検証する。
 *
 * 収集を始める前や、ジャンルを総入れ替えした直後は必ず0件から始まる。
 * ここで伸び率の基準が Python の inf のまま埋まると、JS では未定義の
 * 識別子になってスクリプトが丸ごと止まり、チップも一覧も出なくなる。
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
const chips = [...doc.querySelectorAll('.chip')];
const declared = Number((doc.querySelector('.ver').textContent.match(/(\d+)ジャンル/) || [])[1]);
check('見出しがジャンル数を名乗る', declared > 0, doc.querySelector('.ver').textContent);
// 0件でもジャンルを出さないと、対象が無いツールに見えてしまう
check('「すべて」＋設定のジャンルが並ぶ', chips.length === declared + 1,
      { chips: chips.length, declared });
check('全ジャンルが「収集待ち」', chips.slice(1).every(c => c.classList.contains('pending')),
      chips.slice(1).filter(c => !c.classList.contains('pending')).length);
const bars = [...doc.querySelectorAll('.bar-row')];
check('棒もジャンルの数だけ並ぶ', bars.length === declared, bars.length);
check('棒の長さは全部0',
      bars.every(b => parseFloat(b.querySelector('.bar-fill').style.width) === 0),
      bars.map(b => b.querySelector('.bar-fill').style.width));
check('全部「収集待ち」と出る',
      bars.every(b => b.querySelector('.bar-count').textContent === '収集待ち'),
      bars.map(b => b.querySelector('.bar-count').textContent));

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
chips[0].dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
check('チップを押しても落ちない', errors.length === 0, errors);

console.log(`\n結果: ${pass} pass / ${fail} fail`);
process.exit(fail === 0 ? 0 : 1);
