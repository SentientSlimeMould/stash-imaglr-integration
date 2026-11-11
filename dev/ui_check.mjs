// SPDX-License-Identifier: AGPL-3.0-only
// The plugin's UI in a real browser: every page loads, and the interactive parts work (dialogs, the editor,
// likes, infinite scroll, a collection import with its progress and toast), at desktop and phone width, with no
// script error. Run after e2e.py against the same test Stash (it relies on the blog, likes and collections that
// leaves behind; it queues an image and a marker itself if none are, and takes them off again):
//
//   node dev/ui_check.mjs 9931            # CHROME=/path/to/chrome to choose the browser
//
// Drives headless Chrome over the DevTools protocol with Node's own WebSocket: no dependencies.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const port = process.argv[2] || "9931";
const BASE = `http://127.0.0.1:${port}`;
const ROUTE = "/plugins/imaglr-integration";

function chromePath() {
  if (process.env.CHROME) return process.env.CHROME;
  const mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  if (existsSync(mac)) return mac;
  for (const name of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) {
    for (const dir of (process.env.PATH || "").split(":")) if (existsSync(join(dir, name))) return join(dir, name);
  }
  throw new Error("Chrome not found: set CHROME");
}

// --- a small DevTools client -------------------------------------------------------------------------------------

const profile = mkdtempSync(join(tmpdir(), "imaglr-ui-"));
const chrome = spawn(chromePath(), ["--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run",
  "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"],
{ stdio: ["ignore", "ignore", "pipe"] });
const wsUrl = await new Promise((resolve, reject) => {
  let seen = "";
  chrome.stderr.on("data", (d) => {
    seen += d;
    const m = seen.match(/DevTools listening on (ws:\/\/\S+)/);
    if (m) resolve(m[1]);
  });
  chrome.on("exit", (code) => reject(new Error(`Chrome exited (${code}): ${seen.slice(-500)}`)));
});

const ws = new WebSocket(wsUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let nextId = 0;
const pending = new Map();
const listeners = [];
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id !== undefined && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
  } else if (msg.method) for (const l of listeners) l(msg);
};
function send(method, params = {}, sessionId) {
  const id = ++nextId;
  ws.send(JSON.stringify({ id, method, params, sessionId }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
const page = (method, params) => send(method, params, sessionId);
await page("Runtime.enable");
await page("Log.enable");
await page("Page.enable");

// Script errors fail the check; failed requests are listed but don't (the fake's pictures can't always load).
const problems = [];
const notes = [];
let where = "start";
listeners.push((msg) => {
  if (msg.method === "Runtime.exceptionThrown") {
    const d = msg.params.exceptionDetails;
    problems.push(`${where}: uncaught ${d.exception?.description?.split("\n")[0] ?? d.text}`);
  } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
    const text = msg.params.args.map((a) => a.value ?? a.description ?? "").join(" ");
    problems.push(`${where}: console.error ${text.slice(0, 300)}`);
  } else if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
    notes.push(`${where}: ${msg.params.entry.text.slice(0, 200)} ${msg.params.entry.url ?? ""}`);
  }
});

async function js(expression) {
  const r = await page("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(`${expression.slice(0, 80)}: ${r.exceptionDetails.exception?.description ?? r.exceptionDetails.text}`);
  return r.result.value;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(what, expression, timeout = 15000) {
  const end = Date.now() + timeout;
  for (;;) {
    const v = await js(expression).catch(() => undefined);
    if (v) return v;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await sleep(200);
  }
}
async function open(path) {
  where = path;
  await js("window.__leaving = true").catch(() => undefined); // so the old page isn't mistaken for the new one
  await page("Page.navigate", { url: BASE + path });
  await waitFor("the page", "!window.__leaving && document.readyState === 'complete' && !!document.querySelector('.main, #root > *')");
}
/** Clicks the first visible element matching the selector (and containing the text, if given); says what it hit. */
async function click(selector, text = "") {
  return waitFor(`${selector} ${text}`, `(() => {
    const el = [...document.querySelectorAll(${JSON.stringify(selector)})]
      .find((e) => e.offsetParent !== null && e.textContent.includes(${JSON.stringify(text)}) && !e.disabled);
    if (!el) return;
    el.scrollIntoView({ block: "center" });
    el.click();
    const dialog = el.closest('.modal')?.querySelector('.modal-title')?.textContent;
    return (dialog ? dialog + ' > ' : '') + (el.textContent.trim().slice(0, 40) || el.tagName.toLowerCase()); // never empty: "" would retry
  })()`);
}
/** Clicks a footer button of the open dialog whose title starts with `title`, never another dialog's (a fresh
 *  Stash shows dialogs of its own). */
const isDialog = (which) => which.startsWith(".")
  ? `((m) => !!m.querySelector(${JSON.stringify(which)}) || m.matches(${JSON.stringify(which)}))`
  : `((m) => (m.querySelector('.modal-title')?.textContent || '').startsWith(${JSON.stringify(which)}))`;
async function clickIn(title, button) {
  return waitFor(`"${button}" in "${title}"`, `(() => {
    const dialog = [...document.querySelectorAll('.modal.show')].find(${isDialog(title)});
    const el = dialog && [...dialog.querySelectorAll('.modal-footer button')]
      .find((e) => e.textContent.includes(${JSON.stringify(button)}) && !e.disabled);
    if (el) { el.click(); return true; }
  })()`);
}
/** Waits until no dialog with that title (prefix) is open. */
const closed = (title) => waitFor(`"${title}" to close`, `![...document.querySelectorAll('.modal.show')].some(${isDialog(title)})`, 5000);
const opened = (title, timeout) => waitFor(`"${title}"`, `[...document.querySelectorAll('.modal.show')].some(${isDialog(title)})`, timeout);
const count = (selector) => js(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
/** Stash's own GraphQL, for test data. */
async function gql(query, variables = {}) {
  const r = await (await fetch(`${BASE}/graphql`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ query, variables }) })).json();
  if (r.errors) throw new Error(JSON.stringify(r.errors));
  return r.data;
}
/** Puts one image and one marker in the queue (the imaglr tag) if that tab is empty; returns how to undo it. */
async function queueSome() {
  const tag = (await gql('{findTags(tag_filter:{name:{value:"imaglr",modifier:EQUALS}}){tags{id image_count scene_marker_count}}}')).findTags.tags[0];
  if (!tag) throw new Error("no imaglr tag (run e2e.py first)");
  const undo = [];
  if (!tag.image_count) {
    const id = (await gql("{findImages(filter:{per_page:1}){images{id}}}")).findImages.images[0].id;
    await gql("mutation($ids:[ID!],$t:[ID!]){bulkImageUpdate(input:{ids:$ids,tag_ids:{ids:$t,mode:ADD}}){id}}", { ids: [id], t: [tag.id] });
    undo.push(() => gql("mutation($ids:[ID!],$t:[ID!]){bulkImageUpdate(input:{ids:$ids,tag_ids:{ids:$t,mode:REMOVE}}){id}}", { ids: [id], t: [tag.id] }));
  }
  if (!tag.scene_marker_count) {
    const m = (await gql("{findSceneMarkers(filter:{per_page:1}){scene_markers{id tags{id}}}}")).findSceneMarkers.scene_markers[0];
    const tags = m.tags.map((t) => t.id);
    await gql("mutation($id:ID!,$t:[ID!]){sceneMarkerUpdate(input:{id:$id,tag_ids:$t}){id}}", { id: m.id, t: [...tags, tag.id] });
    undo.push(() => gql("mutation($id:ID!,$t:[ID!]){sceneMarkerUpdate(input:{id:$id,tag_ids:$t}){id}}", { id: m.id, t: tags }));
  }
  return async () => { for (const u of undo) await u(); };
}
const modalTitle = () => js("[...document.querySelectorAll('.modal.show .modal-title')].map((e) => e.textContent).join(' | ')");

// --- the checks --------------------------------------------------------------------------------------------------

let passed = 0;
const failed = [];
async function check(name, fn) {
  const before = problems.length;
  try {
    await fn();
    if (problems.length > before) throw new Error(problems.slice(before).join("; "));
    passed++;
    console.log(`  ok: ${name}`);
  } catch (e) {
    failed.push(name);
    console.log(`  FAIL: ${name}: ${e.message}`);
  }
}

async function pages(width) {
  const phone = width < 600;
  await page("Emulation.setDeviceMetricsOverride", { width, height: phone ? 844 : 1000, deviceScaleFactor: 1, mobile: phone });
  const fits = `document.querySelector('.imaglr-page').scrollWidth <= document.querySelector('.imaglr-page').clientWidth + 1`;
  console.log(`pages at ${width} px`);
  for (const [tab, ready] of [
    ["clips", ".imaglr-grid-card, .imaglr-empty"],
    ["images", ".imaglr-grid-card, .imaglr-empty"],
    ["sent", ".imaglr-sent, .imaglr-grid-card, .imaglr-empty, table"],
    ["feed", ".imaglr-post"],
    ["likes", ".imaglr-sync"],
    ["collections", ".imaglr-grid-card"],
    ["explore&tag=Beach", ".imaglr-post, .imaglr-feed-end"],
  ]) {
    await check(`${tab} loads${phone ? " and fits the screen" : ""}`, async () => {
      await open(`${ROUTE}?tab=${tab}`);
      await waitFor(ready, `!!document.querySelector(${JSON.stringify(ready)})`);
      if (phone && !(await js(fits))) throw new Error("wider than the screen");
    });
  }
  for (const [path, ready] of [["/images", ".image-card, .wall-item"], ["/scenes/markers", ".scene-marker-card, .wall-item"]]) {
    await check(`Stash's ${path}, which the plugin adds to`, async () => {
      await open(path);
      await waitFor("its cards", `!!document.querySelector(${JSON.stringify(ready)})`);
      if (!phone) await waitFor("the imaglr menu item", "[...document.querySelectorAll('.navbar button')].some((b) => b.textContent.trim() === 'imaglr')");
    });
  }
}

const unqueue = await queueSome();
try {
  await pages(1280);

  console.log("interactions");
  await open(`${ROUTE}?tab=clips`);
  await sleep(1500);
  const foreign = await js("[...document.querySelectorAll('.modal.show')].map((m) => m.textContent.slice(0, 120)).join(' | ')");
  if (foreign) console.log(`  (a dialog that isn't the plugin's is open: ${foreign})`);
  await check("Settings opens and closes", async () => {
    await open(`${ROUTE}?tab=clips`);
    await click(".imaglr-page-header button", "Settings");
    await opened("imaglr settings");
    await clickIn("imaglr settings", "Close");
    await closed("imaglr settings");
  });
  for (const tab of ["clips", "images"]) {
    await check(`the ${tab} editor opens from a card and cancels`, async () => {
      await open(`${ROUTE}?tab=${tab}`);
      await click(".imaglr-grid-card a[href*='open=']").catch(async (e) => {
        throw new Error(`${e.message}; on ${await js("location.href")}, cards: ${await js("JSON.stringify([...document.querySelectorAll('.imaglr-grid-card a')].map((a) => [a.getAttribute('href'), a.offsetParent !== null]))")}`);
      });
      await opened(".imaglr-editor-footer"); // the editor (Settings shares its dialog class, not its footer)
      if (tab === "clips") await waitFor("the clip's video", "!!document.querySelector('.imaglr-editor video')");
      await clickIn(".imaglr-editor-footer", "Cancel");
      await closed(".imaglr-editor-footer");
    });
  }
  await check("page buttons above and below the list, Stash's own", async () => {
    await open(`${ROUTE}?tab=sent`);
    await js(`localStorage.setItem("imaglr.controls.sent", JSON.stringify({ perPage: 1 }))`);
    try {
      await open(`${ROUTE}?tab=sent`);
      // Stash's Pagination has First and Last buttons (the plugin's fallback doesn't); v0.32 loads it on demand
      await waitFor("Stash's pager above", "!!document.querySelector('.pagination-index-container .pagination button[title=First]')");
      await waitFor("the index line", "/of \\d/.test(document.querySelector('.pagination-index-container .paginationIndex')?.textContent || '')");
      await waitFor("Stash's pager below", "!!document.querySelector('.pagination-footer .pagination button[title=First]')");
    } finally {
      await js(`localStorage.removeItem("imaglr.controls.sent")`);
    }
  });
  await check("editor: Clear all is away from the tag box, and leaving with changes asks first", async () => {
    await open(`${ROUTE}?tab=images`);
    await click(".imaglr-grid-card a[href*='open=']");
    await opened(".imaglr-editor-footer");
    await waitFor("the tags", "!!document.querySelector('.imaglr-tag-select .react-select__multi-value')");
    if (await count(".imaglr-tag-select .react-select__clear-indicator")) throw new Error("the clear-all × is still in the tag box");
    await click(".imaglr-tags-header button", "Clear all");
    await waitFor("no tags", "!document.querySelector('.imaglr-tag-select .react-select__multi-value')");
    await click(".imaglr-editor a[title='Open in Stash']");
    await opened("Leave without saving?");
    await clickIn("Leave without saving?", "Cancel");
    await closed("Leave without saving?");
    if (!(await js("location.pathname")).includes(ROUTE)) throw new Error("left the editor");
    await clickIn(".imaglr-editor-footer", "Cancel");
    await closed(".imaglr-editor-footer");
  });
  await check("editor: Publish now's confirmation is in front, the editor behind it can't be tapped", async () => {
    await open(`${ROUTE}?tab=images`);
    await click(".imaglr-grid-card a[href*='open=']");
    await opened(".imaglr-editor-footer");
    await click(".imaglr-segmented button", "Published");
    await click(".imaglr-editor-footer button", "Publish now");
    await opened("Publish now");
    const hit = await js(`(() => { const c = [...document.querySelectorAll('.imaglr-editor-footer button')].find((b) => b.textContent.includes('Cancel'));
      const r = c.getBoundingClientRect(); return c.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); })()`);
    if (hit) throw new Error("the editor's Cancel can be tapped while the confirmation is open");
    await clickIn("Publish now", "Cancel");
    await closed("Publish now");
    await clickIn(".imaglr-editor-footer", "Cancel"); // the action change is dropped
    await closed(".imaglr-editor-footer");
  });
  await check("editor: a picture in a post of several opens in Stash's lightbox, in front", async () => {
    await open(`${ROUTE}?tab=images`);
    await waitFor("cards", "!!document.querySelector('.imaglr-grid-card')");
    const ids = await js("[...new Set([...document.querySelectorAll('.imaglr-grid-card a[href*=\"open=\"]')].map((a) => new URL(a.href).searchParams.get('open')))]");
    let undo = null;
    try {
      if (ids.length < 2) { // queue a second image, as queueSome does
        const tag = (await gql('{findTags(tag_filter:{name:{value:"imaglr",modifier:EQUALS}}){tags{id}}}')).findTags.tags[0];
        // one of the test media's own images (not a post saved from imaglr), not queued yet
        const img = (await gql(`{findImages(image_filter:{path:{value:"/saved/",modifier:EXCLUDES},
          tags:{value:["${tag.id}"],modifier:EXCLUDES}},filter:{per_page:1,sort:"path"}){images{id}}}`)).findImages.images[0];
        await gql("mutation($ids:[ID!],$t:[ID!]){bulkImageUpdate(input:{ids:$ids,tag_ids:{ids:$t,mode:ADD}}){id}}", { ids: [img.id], t: [tag.id] });
        undo = () => gql("mutation($ids:[ID!],$t:[ID!]){bulkImageUpdate(input:{ids:$ids,tag_ids:{ids:$t,mode:REMOVE}}){id}}", { ids: [img.id], t: [tag.id] });
        await open(`${ROUTE}?tab=images`);
        await waitFor("two cards", "document.querySelectorAll('.imaglr-grid-card').length >= 2");
        ids.splice(0, ids.length, ...await js("[...new Set([...document.querySelectorAll('.imaglr-grid-card a[href*=\"open=\"]')].map((a) => new URL(a.href).searchParams.get('open')))]"));
      }
      const made = await js(`fetch('/graphql', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({
        query: 'mutation($id: ID!, $args: Map) { runPluginOperation(plugin_id: $id, args: $args) }',
        variables: { id: 'imaglrIntegration', args: { mode: 'post_create', item_ids: ${JSON.stringify(ids.slice(0, 2))} } } }) }).then((r) => r.json())`);
      const post = made.data?.runPluginOperation?.post_id;
      if (!post) throw new Error(`couldn't make a post of two: ${JSON.stringify(made.errors)}`);
      try {
        await open(`${ROUTE}?tab=images&open=${post}`);
        await opened(".imaglr-editor-footer");
        await click(".imaglr-strip-view");
        await waitFor("the lightbox", "!!document.querySelector('.Lightbox img')");
        await waitFor("the lightbox in front", "(() => { const r = document.querySelector('.Lightbox img').getBoundingClientRect(); return !!document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest('.Lightbox'); })()");
        await page("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
        await page("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
        await waitFor("the lightbox to close", "!document.querySelector('.Lightbox')");
        if (!(await count(".imaglr-editor-footer"))) throw new Error("the editor closed too");
        await clickIn(".imaglr-editor-footer", "Cancel");
        await closed(".imaglr-editor-footer");
      } finally {
        await js(`fetch('/graphql', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({
          query: 'mutation($id: ID!, $args: Map) { runPluginOperation(plugin_id: $id, args: $args) }',
          variables: { id: 'imaglrIntegration', args: { mode: 'post_split', post_id: ${JSON.stringify(post)} } } }) }).then((r) => r.json())`);
      }
    } finally {
      if (undo) await undo();
    }
  });
  await check("clip editor: In and Out step by one frame", async () => {
    await open(`${ROUTE}?tab=clips`);
    await click(".imaglr-grid-card a[href*='open=']");
    await opened(".imaglr-editor-footer");
    await waitFor("the clip's video", "!!document.querySelector('.imaglr-editor video')?.duration");
    const inBox = "document.querySelector('.imaglr-time-input').value";
    const before = await js(inBox);
    await click(".imaglr-time-buttons button", "+1 frame");
    await waitFor("In one frame on", `${inBox} !== ${JSON.stringify(before)}`);
    await click(".imaglr-time-buttons button", "−1 frame");
    await waitFor("In back where it was", `${inBox} === ${JSON.stringify(before)}`);
    await clickIn(".imaglr-editor-footer", "Cancel");
    await closed(".imaglr-editor-footer");
  });
  await check("the feed loads more as you scroll", async () => {
    await open(`${ROUTE}?tab=feed`);
    await waitFor("posts", "document.querySelectorAll('.imaglr-post').length > 0");
    const first = await count(".imaglr-post");
    await js("window.scrollTo(0, document.body.scrollHeight)");
    await waitFor("more posts, or the end", `document.querySelectorAll('.imaglr-post').length > ${first} || !!document.querySelector('.imaglr-feed-end')`);
  });
  await check("like and unlike a post", async () => {
    await open(`${ROUTE}?tab=feed`);
    await waitFor("posts", "!!document.querySelector('.imaglr-post .imaglr-like')");
    const like = "document.querySelector('.imaglr-post .imaglr-like')";
    const liked = await js(`${like}.classList.contains('imaglr-liked')`);
    for (const want of [!liked, liked]) { // and back, leaving the likes as they were
      await waitFor("the like button", `!${like}.disabled`);
      await js(`${like}.click()`);
      await waitFor(want ? "liked" : "unliked", `${like}.classList.contains('imaglr-liked') === ${want} && !${like}.disabled`);
    }
  });
  await check("Save opens the review and cancels", async () => {
    await open(`${ROUTE}?tab=feed`);
    await click(".imaglr-post-actions button", "Save");
    await opened("Save to your library");
    await waitFor("its tag rows", "!document.querySelector('.modal.show.imaglr-review .modal-footer .btn-primary')?.disabled");
    await clickIn("Save to your library", "Cancel");
    await closed("Save to your library");
  });
  await check("Sync likes asks first and cancels", async () => {
    await open(`${ROUTE}?tab=likes`);
    // Straight away: tapped before the page has its save settings, it waits for them rather than asking for a folder.
    await click(".imaglr-sync button", "Sync likes");
    await opened("Sync your likes").catch(async (e) => { throw new Error(`${e.message}; open: "${await modalTitle()}"`); });
    await clickIn("Sync your likes", "Cancel");
    await closed("Sync your likes");
  });
  await check("a collection imports, with progress and a toast", async () => {
    await open(`${ROUTE}?tab=collections`);
    await click(".imaglr-grid-card a", "After dark");
    await waitFor("its posts", "!!document.querySelector('.imaglr-post')");
    await click(".imaglr-sync button", "Import to library");
    await opened("Import After dark");
    await clickIn("Import After dark", "Import");
    await closed("Import After dark");
    await waitFor("the toast when it ends", "/Last import|import/i.test(document.querySelector('.toast')?.textContent || '')", 60000);
    await waitFor("the count afterwards", "/All in your library|in your library/.test(document.querySelector('.imaglr-sync')?.textContent || '')");
    await waitFor("the button back", "!!document.querySelector('.imaglr-sync button.btn-primary')");
  });

  await pages(390);
} finally {
  await unqueue().catch((e) => console.log(`  (couldn't take the test items off the queue: ${e.message})`));
  ws.close();
  const exited = new Promise((r) => chrome.once("exit", r));
  chrome.kill();
  await exited;
  try { rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 }); } catch { /* Chrome's helpers may still be closing; it's a temp folder */ }
}

if (notes.length) console.log(`requests that failed (not counted):\n  ${[...new Set(notes)].slice(0, 15).join("\n  ")}`);
if (failed.length) {
  console.log(`ui_check: ${failed.length} failed, ${passed} passed`);
  process.exit(1);
}
console.log(`ui_check: all ${passed} checks passed`);
