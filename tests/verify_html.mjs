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
const chips = [...doc.querySelectorAll('.chip')];
check('chipは3ジャンル', chips.length === 3, chips.map(c=>c.textContent));
const facial = chips.find(c => c.textContent === 'フェイシャル');
facial.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
check('フェイシャルのみ3件', n() === 3, { count: n(), users: users() });
check('chipにonクラス', facial.classList.contains('on'), facial.className);
facial.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
check('解除で8件に戻る', n() === 8, n());

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
check('ジャンルはタイルに混ざっていない',
      !labels.some(l => ['薄毛', '育毛', 'フェイシャル'].includes(l)), labels);
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
check('ジャンルの数だけ棒が並ぶ', bars.length === 3, bars.length);
check('見出しが出る', doc.querySelector('.breakdown-title').textContent === 'ジャンル別', null);
const widths = bars.map(b => parseFloat(b.querySelector('.bar-fill').style.width));
check('最多ジャンルが100%', Math.max(...widths) === 100, widths);
check('棒の長さが件数順に並ぶ', widths.every((w, i) => i === 0 || widths[i - 1] >= w), widths);
check('件数が数字で出る', bars.every(b => /^\d+ 件$/.test(b.querySelector('.bar-count').textContent)),
      bars.map(b => b.querySelector('.bar-count').textContent));
check('ジャンル名が途中で割れない', /\.bar-name\s*\{[^}]*white-space:\s*nowrap/s.test(css9), null);

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
