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
check('カード10件', n() === 10, n());
check('件数表示', doc.getElementById('count').textContent === '10 件を表示', doc.getElementById('count').textContent);
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
check('7日以内(168h)で7件', n() === 7, { count: n(), users: users() });
per.value = '30'; fire(per, 'change');
check('30日以内(720h)で9件[700h=29.2日のp8含む]', n() === 9, { count: n(), users: users() });
per.value = '0'; fire(per, 'change');
check('全期間に戻すと10件', n() === 10, n());

console.log('--- 4. ジャンルのタブは出さない ---');
// ジャンルと掛け合わせのチップ列は廃止した。検索窓に語を打って探す
check('ジャンルのチップ列が無い', doc.getElementById('genres') === null, null);
check('掛け合わせのチップ列が無い', doc.getElementById('modifiers') === null, null);
check('チップが1つも無い', doc.querySelectorAll('.chip').length === 0, doc.querySelectorAll('.chip').length);
check('ジャンル別の棒グラフが無い',
      doc.querySelector('.breakdown') === null && doc.querySelectorAll('.bar-row').length === 0, null);

console.log('--- 4b. 見出しのジャンル数と入力候補 ---');
// データにある数ではなく、設定にある数を出す。でないと収集が一周する前は
// 対象がフィクスチャの4ジャンルだけに見えてしまう
const WITH_DATA = 4;   // フィクスチャがデータを持つジャンル数（育毛/エステティシャン/ヘッドスパ/セラピスト）
const declared = Number((doc.querySelector('.ver').textContent.match(/(\d+)ジャンル/) || [])[1]);
check('見出しがジャンル数を名乗る', declared > 0, doc.querySelector('.ver').textContent);
check('データの数ではなく設定の数を名乗る', declared > WITH_DATA, doc.querySelector('.ver').textContent);
const suggest = [...doc.querySelectorAll('#genre-suggest .suggest-item')].map(o => o.textContent);
check('入力候補に設定のジャンルが全部並ぶ', suggest.length === declared, { suggest: suggest.length, declared });
check('検索窓と入力候補がつながっている', doc.getElementById('q').getAttribute('aria-controls') === 'genre-suggest', null);
// <datalist> は iPhone の Safari などで一覧が出ないので使わない
check('datalist を使っていない', doc.querySelector('datalist') === null && !doc.getElementById('q').hasAttribute('list'), null);

console.log('--- 4c. 入力候補の出し入れ（スマホでも出る自前の一覧） ---');
const qs = doc.getElementById('q');
const box = doc.getElementById('genre-suggest');
const shownItems = () => [...box.querySelectorAll('.suggest-item')].filter(li => !li.hidden).map(li => li.textContent);
check('最初は閉じている', box.hidden === true, box.hidden);
qs.dispatchEvent(new window.FocusEvent('focus'));
check('タップ（フォーカス）で開く', box.hidden === false && qs.getAttribute('aria-expanded') === 'true', box.hidden);
check('空欄なら全ジャンルが出る', shownItems().length === declared, shownItems().length);
qs.value = 'へっど'; fire(qs, 'input');
check('打ちかけの語で絞る（ひらがなでも当たる）', shownItems().join('/') === 'ヘッドスパ', shownItems());
qs.value = 'ざざざ'; fire(qs, 'input');
check('当たる候補が無ければ閉じる', box.hidden === true, shownItems());
qs.value = '頭皮 へっど'; fire(qs, 'input');
check('最後の語で絞る', shownItems().join('/') === 'ヘッドスパ', shownItems());
// タップで選ぶ。押した瞬間にフォーカスが外れて一覧が閉じないこと
const item = [...box.querySelectorAll('.suggest-item')].find(li => li.textContent === 'ヘッドスパ');
const md = new window.MouseEvent('mousedown', { bubbles: true, cancelable: true });
item.dispatchEvent(md);
check('押した瞬間はフォーカスを動かさない', md.defaultPrevented, null);
item.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
check('選ぶと最後の語が置き換わる', qs.value === '頭皮 ヘッドスパ', qs.value);
check('選ぶと閉じる', box.hidden === true && qs.getAttribute('aria-expanded') === 'false', box.hidden);
check('選ぶと検索が効く（頭皮かつヘッドスパ＝p3）', n() === 1 && users()[0] === 'ikumou_lab', users());
// 外をタップ（フォーカスが外れる）と閉じる
qs.dispatchEvent(new window.FocusEvent('focus'));
qs.dispatchEvent(new window.FocusEvent('blur'));
check('外をタップすると閉じる', box.hidden === true, box.hidden);
// アプリ内ブラウザでは focus が来ないことがあるので、タップ（click）でも開く
qs.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
check('タップだけでも開く', box.hidden === false, box.hidden);
qs.dispatchEvent(new window.FocusEvent('blur'));
// doctype が無いと互換モードで描かれ、アプリ内ブラウザで崩れる原因になる
check('標準モードで描かれる（doctype あり）', doc.compatMode === 'CSS1Compat', doc.compatMode);
check('言語が日本語', doc.documentElement.getAttribute('lang') === 'ja', doc.documentElement.getAttribute('lang'));
// LINE のアプリ内ブラウザが古い版を出し続けないよう、取り直しを求める
check('キャッシュしない指定がある',
      !!doc.querySelector('meta[http-equiv="Cache-Control"][content*="no-cache"]'), null);
// キーボード操作（PC）
qs.value = ''; fire(qs, 'input');
qs.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
check('↓で先頭の候補が選択状態', box.querySelector('.suggest-item.active') !== null &&
      box.querySelector('.suggest-item.active').textContent === suggest[0],
      box.querySelector('.suggest-item.active') && box.querySelector('.suggest-item.active').textContent);
const ent = new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
qs.dispatchEvent(ent);
check('Enterで選択中の候補に決まる', qs.value === suggest[0] && ent.defaultPrevented, qs.value);
qs.dispatchEvent(new window.FocusEvent('focus'));
qs.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
check('Escで閉じる', box.hidden === true, box.hidden);
// 変換中の Enter では候補を決めない
qs.value = ''; fire(qs, 'input');
qs.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
qs.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, isComposing: true }));
check('変換確定のEnterでは決めない', qs.value === '', qs.value);
qs.dispatchEvent(new window.FocusEvent('blur'));
qs.value = ''; fire(qs, 'input');
qs.dispatchEvent(new window.FocusEvent('blur'));
check('候補を閉じて全件に戻る', box.hidden === true && n() === 10, { hidden: box.hidden, n: n() });
check('入力候補にデータのあるジャンルが入る',
      ['育毛', 'エステティシャン', 'ヘッドスパ', 'セラピスト'].every(g => suggest.includes(g)), suggest);
check('依頼の新ジャンルが候補に入る',
      ['リラク', 'まつ毛パーマ', '腸もみ', 'シミ', 'ハーブピーリング', '姿勢'].every(g => suggest.includes(g)), suggest);
check('掛け合わせ語は候補に出さない', !suggest.includes('経営'), suggest.filter(g => g === '経営'));

console.log('--- 5. 操作は検索窓と2つの選択肢だけ ---');
check('キーワードのドロップダウンが無い', doc.getElementById('keyword') === null, null);
const selects = [...doc.querySelectorAll('.controls select')].map(e => e.id);
check('残る選択肢は並び替えと期間だけ', selects.join(',') === 'sort,period', selects);
check('検索窓がある', doc.getElementById('q') !== null, null);
// 検索窓は操作バーの先頭に置く。このページの主役なので
check('検索窓が並び替えより上にある',
      doc.getElementById('q').compareDocumentPosition(doc.getElementById('sort')) & window.Node.DOCUMENT_POSITION_FOLLOWING,
      null);

console.log('--- 5b. 語で検索する ---');
const q0 = doc.getElementById('q');
const search = (v) => { q0.value = v; fire(q0, 'input'); };
// ジャンル名で探すと、そのジャンルで集めた投稿＋本文に語を含む投稿が出る。
// 育毛ジャンルは p1/p5/p8、本文に「育毛」を含むのはヘッドスパの p3
search('育毛');
check('ジャンル名で探すとジャンルの投稿＋本文一致（4件）', n() === 4, { count: n(), users: users() });
check('本文一致だけの投稿も入る', users().includes('ikumou_lab'), users());
// ジャンル名はひらがなでも当たる
search('へっどすぱ');
check('ひらがなでもジャンルに当たる（3件）', n() === 3, { count: n(), users: users() });
// 全角英字でも、大文字小文字が違っても当たる
search('ＡＧＡ');
check('全角英字でも当たる', n() === 1 && users()[0] === 'aga_memo', users());
search('aga治療');
check('大文字小文字の違いを吸収する', n() === 1, users());
// 空白で区切るとAND。「頭皮」は p1/p3、そのうち「シャンプー」も含むのは p1 だけ
search('頭皮 シャンプー');
check('空白区切りはAND（1件）', n() === 1 && users()[0] === 'hair_clinic_jp', users());
search('頭皮　シャンプー');
check('全角空白でも区切れる', n() === 1, users());
// ジャンルと本文語の組み合わせ（旧「掛け合わせ」の代わり）
search('エステティシャン 売上');
check('ジャンル＋本文語で絞れる', n() === 1 && users()[0] === 'salon_keiei', users());
// 期間とも組み合わさる。育毛の p8 は700時間前
search('育毛');
const per5 = doc.getElementById('period');
per5.value = '7'; fire(per5, 'change');
check('期間とANDで効く', n() === 3 && !users().includes('aga_memo'), users());
per5.value = '0'; fire(per5, 'change');
// ヒント文。ジャンル語で探しているのか、本文を探しているのかが分かる
check('ジャンル語のときはヒントに出る', doc.getElementById('hint').textContent.includes('「育毛」'),
      doc.getElementById('hint').textContent);
search('');
check('空欄に戻すと全件', n() === 10, n());
check('空欄のヒントは全ジャンルの案内', doc.getElementById('hint').textContent.includes('全ジャンル'),
      doc.getElementById('hint').textContent);

// 「検索」ボタン/Enter でページが再読み込みされない
const form = doc.getElementById('search');
q0.value = '育毛';
const ev = new window.Event('submit', { bubbles: true, cancelable: true });
form.dispatchEvent(ev);
check('送信してもページ遷移しない', ev.defaultPrevented, null);
check('送信で検索が効く', n() === 4, n());
// 日本語入力の確定 Enter では検索を走らせない（キーボードが閉じてしまう）
q0.dispatchEvent(new window.Event('compositionstart'));
q0.value = '頭皮';
const ev2 = new window.Event('submit', { bubbles: true, cancelable: true });
form.dispatchEvent(ev2);
check('変換中の送信は無視する', ev2.defaultPrevented && n() === 4, n());
q0.dispatchEvent(new window.Event('compositionend'));
search('');

// ?q= 付きで開くと、その語で検索した状態から始まる
const urlDom = new JSDOM(html, { runScripts: 'dangerously',
  url: 'https://example.com/threads-trend-collector/?q=' + encodeURIComponent('育毛') });
const urlDoc = urlDom.window.document;
check('?q= の語で検索した状態で開く',
      urlDoc.getElementById('q').value === '育毛' && urlDoc.querySelectorAll('.card').length === 4,
      { q: urlDoc.getElementById('q').value, n: urlDoc.querySelectorAll('.card').length });
const uq = urlDoc.getElementById('q');
uq.value = '頭皮'; uq.dispatchEvent(new urlDom.window.Event('input', { bubbles: true }));
check('入力するとURLの ?q= も変わる',
      new urlDom.window.URL(urlDom.window.location.href).searchParams.get('q') === '頭皮',
      urlDom.window.location.href);

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

console.log('--- 9. 集計タイルと最終収集の行は出さない ---');
// 見出しのすぐ下に検索窓を置く。数字のタイルは検索の邪魔になるので廃止した
check('集計タイルが無い', doc.getElementById('summary') === null && doc.querySelectorAll('.stat').length === 0,
      doc.querySelectorAll('.stat').length);
check('最終収集の行が無い', doc.getElementById('stamp') === null && !doc.body.textContent.includes('最終収集'), null);
check('「表示中の投稿」の文言が無い', !doc.body.textContent.includes('表示中の投稿'), null);
check('見出しの次が検索窓', doc.querySelector('header').nextElementSibling.classList.contains('controls'),
      doc.querySelector('header').nextElementSibling.className);
// 上限で絞った版でも、載せた件数だけカードが出る
const trimmedDoc = new JSDOM(fs.readFileSync(process.env.SCRATCH + '/preview_trimmed.html', 'utf8'),
                             { runScripts: 'dangerously' }).window.document;
check('絞り込んだ結果が3件', trimmedDoc.querySelectorAll('.card').length === 3, trimmedDoc.querySelectorAll('.card').length);
check('絞り込んだ版にも蓄積件数の行は出ない', !trimmedDoc.body.textContent.includes('蓄積'), null);

console.log('--- 9c. カードのタグ ---');
const cardTags = [...doc.querySelectorAll('.card')].map(c =>
  [...c.querySelectorAll('.tag')].map(e => e.textContent));
check('同じタグが二重に出ない',
      cardTags.every(t => new Set(t).size === t.length),
      cardTags.filter(t => new Set(t).size !== t.length));
check('タグ自体は出ている', cardTags.flat().length > 0, cardTags.flat().length);
// 検索語をそのまま出すと「オンライン秘書」と「オンライン秘書 経営」が並んで冗長
check('検索語そのものは出さない',
      cardTags.flat().every(t => !t.includes(' ')), cardTags.flat().filter(t => t.includes(' ')));
// タグは収集したジャンル名だけ。検索して見つけた語の由来が分かる
const outside = cardTags.flat().filter(t => !suggest.includes(t));
check('タグはジャンル名のどれか', outside.length === 0, outside);
// 掛け合わせ語のタグは廃止した（p9 は本文に「売上」「集客」を持つが、タグはジャンルだけ）
const keieiCard = [...doc.querySelectorAll('.card')].find(c => c.textContent.includes('salon_keiei'));
check('掛け合わせのタグは付かない',
      [...keieiCard.querySelectorAll('.tag')].map(e => e.textContent).join('/') === 'エステティシャン',
      [...keieiCard.querySelectorAll('.tag')].map(e => e.textContent));

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
