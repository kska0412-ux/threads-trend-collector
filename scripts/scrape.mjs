/**
 * Threads の検索結果をブラウザで開き、投稿を集めて JSON で吐く。
 *
 * 画面の DOM ではなく、Threads のフロントエンド自身が受け取っている JSON
 * レスポンスを傍受して、そこから投稿を拾う（extract.mjs 参照）。
 * クラス名の変更で壊れないようにするため。
 *
 * 初回はログインが必要:
 *   node scripts/scrape.mjs --login
 *
 * 収集:
 *   node scripts/scrape.mjs --keywords config/keywords.json --out data/raw.json
 *
 * 主なオプション:
 *   --headful      ブラウザを表示して動きを見る
 *   --delay 5      キーワード間の待機秒数（既定5秒）
 *   --dump-dir DIR 生レスポンスを保存する（抽出が空だったときの原因調査用）
 *   --limit N      先頭N個のキーワードだけ処理する（試運転用）
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { chromium } from "playwright";
import { extractFromBody } from "./extract.mjs";
import { collectWithRetry, isFatal } from "./retry.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const PROFILE_DIR = path.join(ROOT, ".browser-profile");

// 検索URL。Threads側の仕様が変わったらここを直す。
const SEARCH_URL = (kw) =>
  `https://www.threads.com/search?q=${encodeURIComponent(kw)}&serp_type=default`;

// インストール済みの Google Chrome を使う。実ブラウザの方が表示が安定する。
const CHROME_CANDIDATES = [
  process.env.THREADS_CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);

function parseArgs(argv) {
  const args = { delay: 5, limit: 0, headful: false, login: false, minPosts: 5 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--login") args.login = true;
    else if (a === "--headful") args.headful = true;
    else if (a === "--keywords") args.keywords = argv[++i];
    else if (a === "--out") args.out = argv[++i];
    else if (a === "--dump-dir") args.dumpDir = argv[++i];
    else if (a === "--delay") args.delay = Number(argv[++i]);
    else if (a === "--limit") args.limit = Number(argv[++i]);
    else if (a === "--min-posts") args.minPosts = Number(argv[++i]);
  }
  return args;
}

function findChrome() {
  for (const p of CHROME_CANDIDATES) if (p && fs.existsSync(p)) return p;
  return null;   // Playwright 同梱の Chromium にまかせる
}

function loadKeywordPairs(file) {
  const config = JSON.parse(fs.readFileSync(file, "utf8"));
  const pairs = [];
  for (const [genre, entry] of Object.entries(config.genres || {})) {
    // 新形式は {keywords: [...], required_any: [...]}、旧形式は配列そのもの
    const keywords = Array.isArray(entry) ? entry : entry.keywords || [];
    for (const kw of keywords) pairs.push({ genre, keyword: kw });
  }
  return pairs;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * cond() が true になるまで待つ。固定時間の待機だと読み込みが終わる前に
 * 先へ進んでしまい、検索結果を取りこぼすため。
 */
async function waitUntil(cond, timeoutMs, intervalMs = 500) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (cond()) return true;
    await sleep(intervalMs);
  }
  return cond();
}

async function openContext({ headful }) {
  const executablePath = findChrome();
  const options = {
    headless: !headful,
    viewport: { width: 1280, height: 900 },
    locale: "ja-JP",
    timezoneId: "Asia/Tokyo",
  };
  if (executablePath) options.executablePath = executablePath;

  try {
    return await chromium.launchPersistentContext(PROFILE_DIR, options);
  } catch (e) {
    const msg = e.message.split("\n")[0];
    throw new Error(
      `ブラウザを起動できませんでした: ${msg}\n` +
      `  Chrome を閉じてから再実行してください。それでも駄目なら\n` +
      `  THREADS_CHROME_PATH に Chrome の実行ファイルを指定してください。`
    );
  }
}

/** 手動ログイン用。ブラウザを開いて、閉じられるまで待つ。 */
async function runLogin() {
  console.log("ブラウザを開きます。Threads にログインしてください。");
  console.log("ログインが終わったらブラウザを閉じてください。セッションは保存されます。");
  const context = await openContext({ headful: true });
  const page = context.pages()[0] || (await context.newPage());
  await page.goto("https://www.threads.com/login", { waitUntil: "domcontentloaded" });

  await new Promise((resolve) => {
    context.on("close", resolve);
    page.on("close", resolve);
  });
  console.log(`セッションを保存しました: ${PROFILE_DIR}`);
}

/** 1キーワード分の検索結果を集める。 */
async function collectKeyword(page, keyword, { dumpDir }) {
  const bodies = [];
  const posts = new Map();   // レスポンスが届くたびに随時抽出していく

  const onResponse = async (response) => {
    const url = response.url();
    if (!url.includes("threads.com") && !url.includes("threads.net")) return;
    const type = (response.headers()["content-type"] || "").toLowerCase();
    // 検索結果は GraphQL の JSON で来るのが基本だが、最初の1ページが
    // HTML に埋め込まれて来ることもあるので HTML も読む。
    if (!type.includes("json") && !type.includes("html") && !url.includes("/graphql")) return;
    try {
      const body = await response.text();
      bodies.push(body);
      for (const post of extractFromBody(body)) {
        if (!posts.has(post.id)) posts.set(post.id, post);
      }
    } catch {
      // ナビゲーションで破棄されたレスポンスは読めないことがある。無視して続ける
    }
  };

  page.on("response", onResponse);
  try {
    await page.goto(SEARCH_URL(keyword), { waitUntil: "domcontentloaded", timeout: 90000 });

    if (page.url().includes("/login")) {
      throw new Error("ログインしていません。node scripts/scrape.mjs --login を先に実行してください。");
    }

    // 1件でも入ってくるまで待つ。固定待機だと読み込み前に先へ進んでしまう。
    await waitUntil(() => posts.size > 0, 30000);

    // 増えなくなるまでスクロールして追加ページを読む
    for (let i = 0; i < 3; i++) {
      const before = posts.size;
      await page.mouse.wheel(0, 2500);
      await waitUntil(() => posts.size > before, 10000);
      if (posts.size === before) break;   // もう増えないので打ち切る
    }
  } finally {
    // 飛んでいる最中のレスポンスを取りこぼさないよう、少しだけ待ってから外す
    await sleep(2000);
    page.off("response", onResponse);
  }

  if (dumpDir) {
    fs.mkdirSync(dumpDir, { recursive: true });
    const safe = keyword.replace(/[^\p{L}\p{N}]+/gu, "_");
    fs.writeFileSync(path.join(dumpDir, `${safe}.txt`), bodies.join("\n===RESPONSE===\n"), "utf8");
  }

  return [...posts.values()];
}

async function runCollect(args) {
  if (!args.keywords || !args.out) {
    throw new Error("--keywords と --out は必須です。");
  }

  let pairs = loadKeywordPairs(args.keywords);
  if (args.limit > 0) pairs = pairs.slice(0, args.limit);

  const context = await openContext({ headful: args.headful });
  const page = context.pages()[0] || (await context.newPage());
  const results = [];

  try {
    for (let i = 0; i < pairs.length; i++) {
      const { genre, keyword } = pairs[i];
      const label = `[${i + 1}/${pairs.length}] ${genre} / ${keyword}`;
      const outcome = await collectWithRetry(
        () => collectKeyword(page, keyword, { dumpDir: args.dumpDir }),
        {
          minPosts: args.minPosts,
          onRetry: (reason) => console.log(`${label}: ${reason} / やり直します`),
        }
      );

      if (outcome.error) {
        console.log(`${label}: 失敗 — ${outcome.error}`);
        results.push({ genre, keyword, posts: [], error: outcome.error });
      } else {
        console.log(`${label}: ${outcome.posts.length} 件`);
        results.push({ genre, keyword, posts: outcome.posts, error: null });
      }

      if (isFatal(outcome.lastError)) break;

      // 連続アクセスを避けるため、キーワードごとに間を空ける
      if (i < pairs.length - 1) {
        const jitter = args.delay * (0.8 + Math.random() * 0.4);
        await sleep(jitter * 1000);
      }
    }
  } finally {
    await context.close();
  }

  fs.mkdirSync(path.dirname(args.out), { recursive: true });
  fs.writeFileSync(
    args.out,
    JSON.stringify({ collected_at: new Date().toISOString(), results }, null, 2),
    "utf8"
  );

  const total = results.reduce((n, r) => n + r.posts.length, 0);
  const failed = results.filter((r) => r.error).length;
  console.log(`\n合計 ${total} 件を ${args.out} に書き出しました（失敗 ${failed}/${results.length} キーワード）`);
  return failed === results.length && results.length > 0 ? 1 : 0;
}

const args = parseArgs(process.argv.slice(2));
try {
  if (args.login) {
    await runLogin();
    process.exit(0);
  }
  process.exit(await runCollect(args));
} catch (e) {
  console.error(`[NG] ${e.message}`);
  process.exit(2);
}
