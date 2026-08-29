/**
 * extract.mjs の抽出ロジックを、合成した JSON で検証する。
 * ブラウザも通信も使わないので、単体で常に再現する。
 */
import { extractFromBody, findPosts, looksLikePost, parsePayloads } from "../scripts/extract.mjs";

let pass = 0, fail = 0;
function check(label, cond, actual) {
  if (cond) { pass++; console.log(`  OK   ${label}`); }
  else { fail++; console.log(`  FAIL ${label}  → 実際: ${JSON.stringify(actual)}`); }
}

// Threads/Instagram 系の実際の形に寄せた投稿オブジェクト
const media = (over = {}) => ({
  pk: "3141592653",
  code: "C1abcDEF",
  caption: { text: "生え際が後退してきたら、まず疑うべきは血流です。" },
  like_count: 1250,
  user: { pk: "999", username: "hair_clinic_jp" },
  taken_at: 1756500000,
  ...over,
});

console.log("--- 1. 基本の抽出 ---");
{
  const posts = findPosts({ data: { items: [media()] } });
  check("1件抽出できる", posts.length === 1, posts.length);
  const p = posts[0];
  check("id", p.id === "3141592653", p.id);
  check("username", p.username === "hair_clinic_jp", p.username);
  check("本文", p.text.startsWith("生え際が"), p.text);
  check("いいね数", p.like_count === 1250, p.like_count);
  check("permalinkをcodeから組める", p.permalink === "https://www.threads.com/@hair_clinic_jp/post/C1abcDEF", p.permalink);
  check("timestampがISO+0000形式", /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+0000$/.test(p.timestamp), p.timestamp);
}

console.log("--- 2. 深いネストでも見つかる ---");
{
  const deep = { data: { searchResults: { edges: [
    { node: { thread_items: [{ post: media({ pk: "A" }) }] } },
    { node: { thread_items: [{ post: media({ pk: "B", user: { username: "esthe_mika" } }) }] } },
  ] } } };
  const posts = findPosts(deep);
  check("2件とも見つかる", posts.length === 2, posts.map(p => p.id));
}

console.log("--- 3. 投稿でないものは拾わない ---");
{
  check("like_countだけの物体は不可", !looksLikePost({ like_count: 5 }), null);
  check("usernameが無い物体は不可", !looksLikePost({ like_count: 5, pk: "x", caption: { text: "a" } }), null);
  check("本文キーが無い物体は不可", !looksLikePost({ like_count: 5, pk: "x", user: { username: "u" } }), null);
  check("like_countが文字列なら不可", !looksLikePost(media({ like_count: "1250" })), null);
  check("idが無ければ不可", !looksLikePost({ like_count: 5, user: { username: "u" }, caption: { text: "a" } }), null);
  const mixed = findPosts({ list: [media(), { like_count: 3, label: "集計値" }, { user: { username: "u" } }] });
  check("混在しても投稿だけ1件", mixed.length === 1, mixed.length);
}

console.log("--- 4. 本文の置き場所ゆれに対応 ---");
{
  const a = findPosts({ x: media({ pk: "t1", caption: undefined, text: "textキーに入っている場合" }) });
  check("o.text も拾える", a.length === 1 && a[0].text === "textキーに入っている場合", a);
  const b = findPosts({ x: media({ pk: "t2", caption: { text: "" } }) });
  check("本文が空文字の投稿も拾う（画像のみ投稿）", b.length === 1 && b[0].text === "", b);
  const c = findPosts({ x: media({ pk: "t3", caption: "文字列のcaption" }) });
  check("captionが文字列でも拾える", c.length === 1 && c[0].text === "文字列のcaption", c);
}

console.log("--- 5. 時刻のゆれに対応 ---");
{
  const ms = findPosts({ x: media({ pk: "m1", taken_at: 1756500000000 }) })[0];
  const sec = findPosts({ x: media({ pk: "m2", taken_at: 1756500000 }) })[0];
  check("ミリ秒でも秒でも同じ時刻になる", ms.timestamp === sec.timestamp, [ms.timestamp, sec.timestamp]);
  const none = findPosts({ x: media({ pk: "m3", taken_at: undefined }) })[0];
  check("時刻が無くても落ちない", none.timestamp === null, none.timestamp);
}

console.log("--- 6. 重複の排除 ---");
{
  const posts = findPosts({ a: [media(), media()], b: media() });
  check("同じidは1件にまとまる", posts.length === 1, posts.length);
}

console.log("--- 7. 引用元も個別に拾う ---");
{
  const withQuote = media({ pk: "outer", quoted_post: media({ pk: "inner", user: { username: "quoted_user" } }) });
  const posts = findPosts({ x: withQuote });
  check("本体と引用元の2件", posts.length === 2, posts.map(p => p.id));
  check("引用元のusernameも取れる", posts.some(p => p.username === "quoted_user"), posts.map(p => p.username));
}

console.log("--- 8. 壊れた入力への耐性 ---");
{
  const circular = { name: "root" };
  circular.self = circular;
  circular.post = media({ pk: "c1" });
  let ok = true;
  try { findPosts(circular); } catch { ok = false; }
  check("循環参照で無限ループしない", ok, null);
  check("空文字列は空配列", extractFromBody("").length === 0, null);
  check("JSONでない本文は空配列", extractFromBody("<html>not json</html>").length === 0, null);
  check("nullを渡しても落ちない", findPosts(null).length === 0, null);
}

console.log("--- 9. 改行区切りの複数JSON ---");
{
  const body = [JSON.stringify({ x: media({ pk: "n1" }) }), JSON.stringify({ y: media({ pk: "n2" }) })].join("\n");
  check("2つのJSONから2件", extractFromBody(body).length === 2, extractFromBody(body).map(p => p.id));
  check("parsePayloadsが2つ返す", parsePayloads(body).length === 2, parsePayloads(body).length);
  const mixedBody = "for (;;);\n" + JSON.stringify({ x: media({ pk: "n3" }) });
  check("先頭にゴミ行があっても拾う", extractFromBody(mixedBody).length === 1, extractFromBody(mixedBody));
}

console.log("--- 10. 深すぎるネストは打ち切る ---");
{
  let nested = media({ pk: "deep" });
  for (let i = 0; i < 60; i++) nested = { level: nested };
  check("maxDepth超過では拾わない（暴走防止）", findPosts(nested).length === 0, findPosts(nested).length);
  check("浅ければ拾う", findPosts(nested, { maxDepth: 200 }).length === 1, null);
}

console.log(`\n結果: ${pass} pass / ${fail} fail`);
process.exit(fail === 0 ? 0 : 1);
