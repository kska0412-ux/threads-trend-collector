/**
 * Threads が返す JSON から投稿を抜き出す。
 *
 * DOM のクラス名は難読化されていて頻繁に変わるため、画面ではなく
 * フロントエンドが受け取っている JSON を見る。ただし JSON の構造も
 * 変わりうるので、決め打ちのパスは辿らず「投稿らしい形をしたオブジェクト」を
 * 再帰的に探す。like_count と username と本文を持っていれば投稿とみなす。
 */

/** 投稿とみなすのに必要な条件を満たすか。 */
export function looksLikePost(o) {
  if (!o || typeof o !== "object" || Array.isArray(o)) return false;
  if (typeof o.like_count !== "number") return false;
  if (getUsername(o) === null) return false;
  if (getId(o) === null) return false;
  return getText(o) !== null;
}

function getId(o) {
  for (const k of ["pk", "id", "pk_id"]) {
    const v = o[k];
    if (typeof v === "string" && v) return v;
    if (typeof v === "number") return String(v);
  }
  return null;
}

function getUsername(o) {
  const u = o.user;
  if (u && typeof u === "object" && typeof u.username === "string" && u.username) {
    return u.username;
  }
  if (typeof o.username === "string" && o.username) return o.username;
  return null;
}

function getText(o) {
  // 新旧・複数の置き場所に対応する。空文字は「本文なし」ではなく有効な値として扱う
  // （画像のみの投稿があるため）が、キー自体が無い場合は投稿と認めない。
  if (o.caption && typeof o.caption === "object" && typeof o.caption.text === "string") {
    return o.caption.text;
  }
  if (typeof o.caption === "string") return o.caption;
  if (typeof o.text === "string") return o.text;
  return null;
}

function getTimestamp(o) {
  // taken_at は UNIX 秒。ミリ秒で来る実装もあるので桁で判別する。
  for (const k of ["taken_at", "taken_at_timestamp", "device_timestamp", "publish_date"]) {
    const v = o[k];
    if (typeof v === "number" && v > 0) {
      const seconds = v > 1e12 ? Math.floor(v / 1000) : v;
      return new Date(seconds * 1000).toISOString().replace(".000Z", "+0000");
    }
  }
  if (typeof o.timestamp === "string" && o.timestamp) return o.timestamp;
  return null;
}

function getPermalink(o, username) {
  if (typeof o.permalink === "string" && o.permalink) return o.permalink;
  if (typeof o.code === "string" && o.code && username) {
    return `https://www.threads.com/@${username}/post/${o.code}`;
  }
  return null;
}

/** 投稿オブジェクトを、保存する形に整える。 */
export function normalizePost(o) {
  const username = getUsername(o);
  return {
    id: getId(o),
    username,
    text: getText(o),
    timestamp: getTimestamp(o),
    permalink: getPermalink(o, username),
    like_count: o.like_count,
  };
}

/**
 * 任意の JSON を再帰的に walk して、投稿らしいオブジェクトを全部集める。
 * 同一 id は最初に見つかったものを採用する。
 */
export function findPosts(root, { maxDepth = 40 } = {}) {
  const found = new Map();
  const seen = new WeakSet();

  const walk = (node, depth) => {
    if (depth > maxDepth || node === null || typeof node !== "object") return;
    if (seen.has(node)) return;   // 循環参照よけ
    seen.add(node);

    if (Array.isArray(node)) {
      for (const item of node) walk(item, depth + 1);
      return;
    }

    if (looksLikePost(node)) {
      const post = normalizePost(node);
      if (!found.has(post.id)) found.set(post.id, post);
      // 投稿の中に引用元やリプライがぶら下がることがあるので、下も見る
    }

    for (const key of Object.keys(node)) walk(node[key], depth + 1);
  };

  walk(root, 0);
  return [...found.values()];
}

/**
 * レスポンスの生テキストを JSON として解釈する。
 * Threads は 1レスポンスに複数の JSON を改行区切りで詰めてくることがあるため、
 * まるごと parse に失敗したら行ごとに試す。
 */
export function parsePayloads(body) {
  const out = [];
  const trimmed = (body || "").trim();
  if (!trimmed) return out;

  try {
    out.push(JSON.parse(trimmed));
    return out;
  } catch {
    // 改行区切りの複数 JSON とみなして再挑戦する
  }

  for (const line of trimmed.split("\n")) {
    const s = line.trim();
    if (!s || (s[0] !== "{" && s[0] !== "[")) continue;
    try {
      out.push(JSON.parse(s));
    } catch {
      // 壊れた行は捨てる
    }
  }
  return out;
}

/** レスポンス本文から投稿を抜き出すところまでを一息でやる。 */
export function extractFromBody(body) {
  const posts = [];
  for (const payload of parsePayloads(body)) posts.push(...findPosts(payload));

  const unique = new Map();
  for (const p of posts) if (!unique.has(p.id)) unique.set(p.id, p);
  return [...unique.values()];
}
