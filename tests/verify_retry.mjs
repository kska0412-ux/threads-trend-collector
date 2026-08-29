/** retry.mjs のやり直し判定を検証する。ブラウザも通信も使わない。 */
import { collectWithRetry, isFatal } from "../scripts/retry.mjs";

let pass = 0, fail = 0;
function check(label, cond, actual) {
  if (cond) { pass++; console.log(`  OK   ${label}`); }
  else { fail++; console.log(`  FAIL ${label}  → 実際: ${JSON.stringify(actual)}`); }
}

const nosleep = () => Promise.resolve();
const posts = (n) => Array.from({ length: n }, (_, i) => ({ id: `p${i}` }));
const run = (opts = {}) => (fn) => collectWithRetry(fn, { minPosts: 5, sleep: nosleep, ...opts });

console.log("--- 十分な件数が取れたら1回で終わる ---");
{
  let calls = 0;
  const r = await run()(() => { calls++; return posts(20); });
  check("20件で成功", r.posts.length === 20, r.posts.length);
  check("エラーなし", r.error === null, r.error);
  check("1回しか呼ばない", calls === 1, calls);
}

console.log("--- 件数が少なければやり直す ---");
{
  let calls = 0;
  const r = await run()(() => { calls++; return posts(calls === 1 ? 1 : 20); });
  check("2回呼ぶ", calls === 2, calls);
  check("やり直し後の20件を採用", r.posts.length === 20, r.posts.length);
}

console.log("--- やり直しで減ったら、多い方を残す ---");
{
  const r = await run()((n) => posts(n === 1 ? 3 : 1));
  check("3件の方を採用する", r.posts.length === 3, r.posts.length);
  check("エラー扱いにしない", r.error === null, r.error);
}

console.log("--- 例外からの復帰 ---");
{
  let calls = 0;
  const r = await run()(() => {
    calls++;
    if (calls === 1) throw new Error("page.goto: Timeout 90000ms exceeded.\nCall log: ...");
    return posts(20);
  });
  check("やり直して成功する", r.posts.length === 20, r.posts.length);
  check("エラーは残らない", r.error === null, r.error);
}

console.log("--- 取れた分を例外で捨てない（今回直した不具合） ---");
{
  let calls = 0;
  const r = await run()(() => {
    calls++;
    if (calls === 1) return posts(3);
    throw new Error("page.goto: Timeout");
  });
  check("1回目の3件が残る", r.posts.length === 3, r.posts.length);
  check("成功扱いになる", r.error === null, r.error);
  check("直近の例外は記録されている", r.lastError.includes("Timeout"), r.lastError);
}

console.log("--- 全部失敗したときだけエラー ---");
{
  const r = await run()(() => { throw new Error("page.goto: Timeout 90000ms exceeded."); });
  check("投稿は空", r.posts.length === 0, r.posts);
  check("エラーが立つ", r.error && r.error.includes("Timeout"), r.error);
  check("改行以降は切り落とす", !r.error.includes("\n"), r.error);
}

console.log("--- 未ログインは即座に打ち切る ---");
{
  let calls = 0;
  const r = await run()(() => {
    calls++;
    throw new Error("ログインしていません。node scripts/scrape.mjs --login を先に実行してください。");
  });
  check("やり直さない", calls === 1, calls);
  check("致命的と判定される", isFatal(r.lastError), r.lastError);
  check("isFatalは通常のエラーでは立たない", !isFatal("page.goto: Timeout"), null);
}

console.log("--- 0件が続く場合 ---");
{
  let calls = 0;
  const r = await run()(() => { calls++; return posts(0); });
  check("2回試す", calls === 2, calls);
  check("例外が無ければエラーにはせず、0件として記録する", r.posts.length === 0 && r.error === null, { n: r.posts.length, e: r.error });
}

console.log(`\n結果: ${pass} pass / ${fail} fail`);
process.exit(fail === 0 ? 0 : 1);
