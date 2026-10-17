/* Imaglr Integration for Stash. SPDX-License-Identifier: AGPL-3.0-only
 * Generated from src/ui by scripts/build.mjs. Do not edit. */
"use strict";
(() => {
  // src/ui/shims/react.ts
  var react_default = PluginApi.React;

  // src/ui/lib/posts.ts
  var SAVING = ["queued", "downloading", "scanning"];
  function relativeTime(iso, now = /* @__PURE__ */ new Date()) {
    if (!iso) return "";
    const then = new Date(iso);
    const seconds = (now.getTime() - then.getTime()) / 1e3;
    if (Number.isNaN(seconds)) return "";
    if (seconds < 60) return "now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
    if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)} d`;
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const day = `${then.getUTCDate()} ${months[then.getUTCMonth()]}`;
    return then.getUTCFullYear() === now.getUTCFullYear() ? day : `${day} ${then.getUTCFullYear()}`;
  }
  function savedPath(refs) {
    const ref = refs.find((r) => r.kind === "gallery") ?? refs[0];
    if (!ref) return null;
    return `${ref.kind === "gallery" ? "galleries" : ref.kind === "scene" ? "scenes" : "images"}/${ref.id}`;
  }
  function parseSearch(text) {
    const value = text.trim();
    if (!value) return null;
    const link = value.match(/imaglr\.[a-z.]+\/post\/(\d+)/i) ?? value.match(/^(?:post\s+)?(\d{3,})$/i);
    if (link) return { kind: "post", value: link[1] };
    const profile = value.match(/imaglr\.[a-z.]+\/profile\/([^/?#\s]+)/i);
    if (profile) return { kind: "creator", value: decodeURIComponent(profile[1]) };
    if (value.startsWith("@")) return value.length > 1 ? { kind: "creator", value: value.slice(1).trim() } : null;
    const tag = value.replace(/^#/, "").trim();
    return tag ? { kind: "tag", value: tag } : null;
  }
  var RECENT_SEARCHES = 12;
  function searchLabel(found, typed) {
    return found.kind === "creator" ? `@${found.value}` : found.kind === "tag" ? `#${found.value}` : typed.trim();
  }
  function rememberSearch(recent, label) {
    const key = label.toLowerCase();
    return [label, ...recent.filter((r) => r.toLowerCase() !== key)].slice(0, RECENT_SEARCHES);
  }
  function exploreOptions(text, recent, following, limits = { recent: 6, follow: 8 }) {
    const typed = text.trim();
    const needle = typed.replace(/^[#@]/, "").toLowerCase();
    const groups = [];
    const found = parseSearch(typed);
    if (found) {
      const label = found.kind === "creator" ? `Go to @${found.value}` : found.kind === "tag" ? `Search #${found.value}` : "Open this post";
      groups.push({ label: "", options: [{ value: typed, label, kind: "search" }] });
    }
    const recents = recent.filter((r) => r.toLowerCase() !== typed.toLowerCase() && r.toLowerCase().includes(needle)).slice(0, limits.recent);
    if (recents.length) groups.push({ label: "Recent searches", options: recents.map((r) => ({ value: r, label: r, kind: "recent" })) });
    const seen = new Set(recents.map((r) => r.toLowerCase()));
    const people = following.filter((p) => p.name.toLowerCase().includes(needle) && !seen.has(`@${p.name}`.toLowerCase()) && `@${p.name}`.toLowerCase() !== typed.toLowerCase()).slice(0, limits.follow);
    if (people.length) {
      groups.push({ label: "People you follow", options: people.map((p) => ({ value: `@${p.name}`, label: p.name, kind: "follow", avatar: p.avatar })) });
    }
    return groups;
  }
  function mediaRatio(m) {
    return m.width && m.height ? m.width / m.height : 4 / 5;
  }
  function avatarFallback(url) {
    if (!url) return null;
    const fixed = url.replace(/^(https:\/\/cdn\d{0,3}\.imaglr\.com)\/storage\/avatars\//, "$1/avatars/");
    return fixed === url ? null : fixed;
  }
  function shortCount(n) {
    if (n < 1e3) return String(n);
    if (n < 1e4) return `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}k`;
    return `${Math.round(n / 1e3)}k`;
  }
  function imaglrCredit(urls) {
    const list = urls ?? [];
    const post = list.map((u) => ({ u, m: u.match(/^https?:\/\/(?:www\.)?imaglr\.[a-z.]+\/post\/(\d+)/i) })).find((x) => x.m);
    if (!post) return null;
    const profile = list.map((u) => ({ u, m: u.match(/^https?:\/\/(?:www\.)?imaglr\.[a-z.]+\/profile\/([^/?#]+)/i) })).find((x) => x.m);
    return { postUrl: post.u, postId: post.m[1], creatorUrl: profile?.u ?? null, creator: profile ? decodeURIComponent(profile.m[1]) : null };
  }

  // src/ui/api.ts
  var PLUGIN_ID = "imaglrIntegration";
  function baseUrl(doc = document) {
    const href = doc.querySelector("base")?.getAttribute("href") ?? "/";
    return href.endsWith("/") ? href : href + "/";
  }
  async function gql(query, variables = {}) {
    const response = await fetch(baseUrl() + "graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables })
    });
    if (response.status === 401) {
      const here = window.location.pathname + window.location.search;
      window.location.assign(`${baseUrl()}login?returnURL=${encodeURIComponent(here)}`);
      throw new Error("Please log in to Stash again.");
    }
    if (!response.ok) throw new Error(`Stash returned HTTP ${response.status}`);
    const result = await response.json();
    if (result.errors?.length) {
      throw new Error(result.errors.map((e) => e.message).join("; "));
    }
    return result.data;
  }
  async function runOperation(mode, args = {}) {
    const data = await gql(
      "mutation($id: ID!, $args: Map) { runPluginOperation(plugin_id: $id, args: $args) }",
      { id: PLUGIN_ID, args: { ...args, mode } }
    );
    return data.runPluginOperation;
  }

  // src/ui/ConfirmDialog.tsx
  function ConfirmDialog({ title, accept, variant = "primary", busy, disabled, onAccept, onCancel, children }) {
    const { Modal, Button } = PluginApi.libraries.Bootstrap;
    return /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: () => void 0, keyboard: false }, /* @__PURE__ */ react_default.createElement(Modal.Header, null, /* @__PURE__ */ react_default.createElement(Modal.Title, null, title)), /* @__PURE__ */ react_default.createElement(Modal.Body, null, children), /* @__PURE__ */ react_default.createElement(Modal.Footer, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: onCancel, disabled: busy }, "Cancel"), /* @__PURE__ */ react_default.createElement(Button, { variant, onClick: onAccept, disabled: busy || disabled }, accept)));
  }

  // src/ui/discover/ReblogDialog.tsx
  function ReblogDialog({ postId, creator, blogs, blogId, caption, tags, onClose, onDone }) {
    const { Form } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [list, setList] = react_default.useState(blogs ?? null);
    const [chosen, setChosen] = react_default.useState(blogId ?? blogs?.[0]?.id ?? null);
    const [busy, setBusy] = react_default.useState(false);
    react_default.useEffect(() => {
      if (blogs) return;
      runOperation("blogs_list").then((r) => {
        setList(r.blogs);
        setChosen((c) => c ?? r.blogs[0]?.id ?? null);
      }, () => setList([]));
    }, [blogs]);
    const blog = list?.find((b) => b.id === chosen);
    async function accept() {
      if (!blog) return;
      setBusy(true);
      try {
        await runOperation("reblog", { post_id: postId, blog_id: blog.id, caption: caption ?? void 0, tags: tags ?? void 0 });
        Toast.success(`Reblogged to ${blog.label}.`);
        onDone?.();
        onClose();
      } catch (e) {
        Toast.error(e);
        setBusy(false);
      }
    }
    return /* @__PURE__ */ react_default.createElement(ConfirmDialog, { title: "Reblog", accept: "Reblog", busy, disabled: !blog, onAccept: accept, onCancel: onClose }, list && list.length > 1 ? /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "To"), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        as: "select",
        className: "text-input",
        value: chosen ?? "",
        onChange: (e) => setChosen(Number(e.target.value))
      },
      list.map((b) => /* @__PURE__ */ react_default.createElement("option", { key: b.id, value: b.id }, b.label))
    )) : null, list === null ? /* @__PURE__ */ react_default.createElement("p", { className: "mb-0 text-muted" }, "Loading your blogs\u2026") : blog ? /* @__PURE__ */ react_default.createElement("p", { className: "mb-0" }, "Reblog ", creator ? `@${creator}'s post` : "this post", " to ", blog.label, "? It appears on your blog straight away.") : /* @__PURE__ */ react_default.createElement("p", { className: "mb-0" }, "Add a blog in the plugin's settings first."));
  }

  // src/ui/credit.tsx
  function ImaglrCredit({ urls }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const { Icon } = PluginApi.components;
    const fa = PluginApi.libraries.FontAwesomeSolid;
    const [reblogging, setReblogging] = react_default.useState(false);
    const credit = imaglrCredit(urls);
    if (!credit) return null;
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-credit" }, /* @__PURE__ */ react_default.createElement("h6", null, "From imaglr"), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-credit-links" }, /* @__PURE__ */ react_default.createElement("a", { className: "btn btn-secondary", href: credit.postUrl, target: "_blank", rel: "noopener noreferrer" }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faExternalLinkAlt }), " View the post"), credit.creatorUrl ? /* @__PURE__ */ react_default.createElement("a", { className: "btn btn-secondary", href: credit.creatorUrl, target: "_blank", rel: "noopener noreferrer" }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faUser }), " @", credit.creator) : null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => setReblogging(true) }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faRetweet }), " Reblog")), reblogging ? /* @__PURE__ */ react_default.createElement(ReblogDialog, { postId: credit.postId, creator: credit.creator, onClose: () => setReblogging(false) }) : null);
  }
  var TAB = "imaglr-panel";
  function parts(args) {
    return [args[0], args[args.length - 1]];
  }
  function patchCredit() {
    const { Nav, Tab } = PluginApi.libraries.Bootstrap;
    PluginApi.patch.after("ImageDetailPanel", (...args) => {
      const [props, rendered] = parts(args);
      return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(ImaglrCredit, { urls: props.image?.urls }), rendered);
    });
    PluginApi.patch.after("ScenePage.Tabs", (...args) => {
      const [props, rendered] = parts(args);
      if (!imaglrCredit(props.scene?.urls)) return rendered;
      return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, rendered, /* @__PURE__ */ react_default.createElement(Nav.Item, null, /* @__PURE__ */ react_default.createElement(Nav.Link, { eventKey: TAB }, "imaglr")));
    });
    PluginApi.patch.after("ScenePage.TabContent", (...args) => {
      const [props, rendered] = parts(args);
      if (!imaglrCredit(props.scene?.urls)) return rendered;
      return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, rendered, /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: TAB }, /* @__PURE__ */ react_default.createElement(ImaglrCredit, { urls: props.scene?.urls })));
    });
  }

  // src/ui/routes.ts
  var ROUTE = "/plugins/imaglr-integration";

  // src/ui/lib/imageActions.ts
  var MAX_POST_FILES = 10;
  function galleryIdFromPath(pathname) {
    return pathname.match(/\/galleries\/(\d+)(?:\/|$)/)?.[1] ?? null;
  }
  function addedMessage(result, asOnePost) {
    const noun = (n) => `${n} image${n === 1 ? "" : "s"}`;
    if (asOnePost) return `${noun(result.added + result.already)} added to imaglr as one post.`;
    const parts2 = [`${noun(result.added)} added to imaglr.`];
    if (result.already) parts2.push(`${noun(result.already)} already there.`);
    return parts2.join(" ");
  }

  // src/ui/imageListActions.tsx
  function ImageListWithImaglr({ props, Original }) {
    const Toast = PluginApi.hooks.useToast();
    const { useHistory, useLocation } = PluginApi.libraries.ReactRouterDOM;
    const history = useHistory();
    const location = useLocation();
    const galleryId = props.view === "gallery_images" ? galleryIdFromPath(location.pathname) : null;
    async function add(ids, asOnePost) {
      try {
        const result = await runOperation("add_images", { image_ids: ids, as_one_post: asOnePost });
        Toast.success(addedMessage(result, asOnePost));
        if (asOnePost && result.post_id) history.push(`${ROUTE}?tab=images&open=${result.post_id}`);
      } catch (e) {
        Toast.error(e);
      }
    }
    const operations = [
      {
        text: "Add to imaglr",
        isDisplayed: (_r, _f, ids) => ids.size > 0,
        onClick: (_r, _f, ids) => add([...ids], false),
        postRefetch: true
      },
      {
        text: "Add to imaglr as one post",
        isDisplayed: (_r, _f, ids) => ids.size > 0,
        onClick: async (_r, _f, ids) => {
          if (ids.size > MAX_POST_FILES) {
            Toast.error(`An imaglr post holds up to ${MAX_POST_FILES} images. You've selected ${ids.size}.`);
            return;
          }
          await add([...ids], true);
        },
        postRefetch: true
      }
    ];
    if (galleryId) {
      operations.push({
        text: "Add gallery to imaglr as one post",
        isDisplayed: (_r, _f, ids) => ids.size === 0,
        onClick: async () => {
          try {
            const result = await runOperation("add_gallery", {
              gallery_id: galleryId
            });
            if (result.too_many) {
              Toast.error(
                `This gallery has ${result.too_many} images, and a post holds up to ${MAX_POST_FILES}. Tick the ones you want, then choose "Add to imaglr as one post".`
              );
              return;
            }
            Toast.success(addedMessage(result, true));
            if (result.post_id) history.push(`${ROUTE}?tab=images&open=${result.post_id}`);
          } catch (e) {
            Toast.error(e);
          }
        },
        postRefetch: true
      });
    }
    return /* @__PURE__ */ react_default.createElement(Original, { ...props, extraOperations: [...props.extraOperations ?? [], ...operations] });
  }
  function patchImageLists() {
    PluginApi.patch.instead("FilteredImageList", (props, _context, Original) => /* @__PURE__ */ react_default.createElement(ImageListWithImaglr, { props, Original }));
  }

  // src/ui/icon.ts
  var PATH = "M256 32A224 224 0 1 0 256 480A224 224 0 1 0 256 32ZM256 85.8A170.2 170.2 0 1 1 256 426.2A170.2 170.2 0 1 1 256 85.8ZM256 132.8A123.2 123.2 0 1 0 256 379.2A123.2 123.2 0 1 0 256 132.8ZM282.9 175.4A51.5 51.5 0 1 1 282.9 278.4A51.5 51.5 0 1 1 282.9 175.4Z";
  var imaglrIcon = {
    prefix: "imaglr",
    iconName: "imaglr",
    icon: [512, 512, [], "e001", PATH]
  };

  // src/ui/NavItem.tsx
  function NavItem() {
    const { Nav, Button } = PluginApi.libraries.Bootstrap;
    const { useHistory, useRouteMatch } = PluginApi.libraries.ReactRouterDOM;
    const { Icon } = PluginApi.components;
    const history = useHistory();
    const active = useRouteMatch(ROUTE) ? " active" : "";
    return /* @__PURE__ */ react_default.createElement(Nav.Link, { eventKey: ROUTE, as: "div", className: "col-4 col-sm-3 col-md-2 col-lg-auto" }, /* @__PURE__ */ react_default.createElement(
      Button,
      {
        className: "minimal p-4 p-xl-2 d-flex d-xl-inline-block flex-column justify-content-between align-items-center" + active,
        onClick: () => history.push(ROUTE)
      },
      /* @__PURE__ */ react_default.createElement(
        Icon,
        {
          icon: imaglrIcon,
          className: "nav-menu-icon d-block d-xl-inline mb-2 mb-xl-0"
        }
      ),
      /* @__PURE__ */ react_default.createElement("span", null, "imaglr")
    ));
  }

  // src/ui/lib/video.ts
  var VIDEO_CAP_MB = 500;
  var CODEC_LABELS = { h264: "H.264", hevc: "H.265" };
  var SIZE_OPTIONS = [
    { label: "Original", value: null },
    { label: "720p", value: 1280 },
    { label: "480p", value: 854 }
  ];
  function sizeChoicesFor(sourceEdge) {
    return SIZE_OPTIONS.filter((o) => o.value === null || !sourceEdge || o.value < sourceEdge);
  }
  var TYPICAL_KBPS = [[1920, 6e3], [1280, 3e3], [854, 1500], [640, 900]];
  var FLOOR_KBPS = [[1920, 4e3], [1280, 2e3], [854, 1e3], [640, 600]];
  var HEVC_FACTOR = 0.6;
  var AUDIO_KBPS = 128;
  function lookup(table, longEdge, codec) {
    const row = table.find(([edge]) => edge <= longEdge) ?? table[table.length - 1];
    return Math.round(row[1] * (codec === "hevc" ? HEVC_FACTOR : 1));
  }
  function edgeLabel(longEdge) {
    if (longEdge >= 1920) return "1080p";
    if (longEdge >= 1280) return "720p";
    if (longEdge >= 854) return "480p";
    return `${longEdge} px`;
  }
  function outputEdge(sourceEdge, maxEdge) {
    return Math.min(sourceEdge || 1920, maxEdge ?? 1920, 1920);
  }
  function videoEstimate(seconds, codec, longEdge, muted = false) {
    const s = Math.max(0, seconds);
    const audio = muted ? 0 : AUDIO_KBPS;
    const typical = lookup(TYPICAL_KBPS, longEdge, codec);
    const usualMb = (typical + audio) * s / 8192;
    const label = `${CODEC_LABELS[codec]} at ${edgeLabel(longEdge)}`;
    if (usualMb <= VIDEO_CAP_MB * 0.95 || s === 0) {
      const mb = usualMb < 10 ? Math.max(1, Math.round(usualMb)) : Math.round(usualMb / 5) * 5;
      return { text: `About ${mb} MB as ${label}.`, short: `about ${mb} MB`, warn: false };
    }
    const budget = Math.max(200, Math.round(VIDEO_CAP_MB * 8192 * 0.95 / s - audio));
    const floor = lookup(FLOOR_KBPS, longEdge, codec);
    const rate = budget >= 1e3 ? `${(budget / 1e3).toFixed(1)} Mbit/s` : `${budget} kbit/s`;
    if (budget >= floor) {
      return { text: `Over ${VIDEO_CAP_MB} MB at the usual quality, so it will be encoded at about ${rate} as ${label}, which should still look fine.`, short: `about ${rate}, fine`, warn: false };
    }
    const advice = codec === "h264" && longEdge > 854 ? "Choose a smaller picture or H.265." : longEdge > 854 ? "Choose a smaller picture." : codec === "h264" ? "Choose H.265 or a shorter clip." : "Choose a shorter clip.";
    return { text: `Over ${VIDEO_CAP_MB} MB at the usual quality, so it will be encoded at about ${rate} as ${label}, which will look poor. ${advice}`, short: `about ${rate}, will look poor`, warn: true };
  }

  // src/ui/lib/crop.ts
  var ASPECTS = { original: null, "9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1 };
  var EDGE_NAMES = ["top", "bottom", "left", "right"];
  var MAX_EDGE_PERCENT = 45;
  function emptyEdges() {
    return { top: 0, right: 0, bottom: 0, left: 0 };
  }
  function cropSummary(crop) {
    const parts2 = [];
    if (crop.aspect !== "original") parts2.push(crop.aspect);
    if (hasEdges(crop.edges)) parts2.push("edges trimmed");
    return parts2.join(" \xB7 ");
  }
  function hasEdges(edges) {
    return !!edges && EDGE_NAMES.some((n) => (edges[n] ?? 0) > 0);
  }
  function insetRect(edges) {
    const e = edges ?? emptyEdges();
    const clamp = (v) => Math.min(MAX_EDGE_PERCENT / 100, Math.max(0, v || 0));
    const l = clamp(e.left), t = clamp(e.top);
    const w = Math.max(0.1, 1 - l - clamp(e.right)), h = Math.max(0.1, 1 - t - clamp(e.bottom));
    return { x: l, y: t, w, h };
  }
  function normCrop(srcW, srcH, aspect, position, edges) {
    const box = insetRect(edges);
    const trimmed = box.x > 0 || box.y > 0 || box.w < 1 || box.h < 1;
    const a = ASPECTS[aspect];
    if (a == null || srcW <= 0 || srcH <= 0) return { ...box, axis: "none", cropped: trimmed };
    const s = srcW * box.w / (srcH * box.h);
    if (Math.abs(s - a) < 1e-6) return { ...box, axis: "none", cropped: trimmed };
    let w = 1, h = 1;
    if (a < s) w = a / s;
    else h = s / a;
    const p = Math.min(1, Math.max(0, position));
    return {
      x: box.x + (1 - w) * p * box.w,
      y: box.y + (1 - h) * p * box.h,
      w: w * box.w,
      h: h * box.h,
      axis: w < 1 ? "x" : h < 1 ? "y" : "none",
      cropped: true
    };
  }
  function displayedRect(cw, ch, srcW, srcH) {
    if (srcW <= 0 || srcH <= 0 || cw <= 0 || ch <= 0) return { dx: 0, dy: 0, dw: cw, dh: ch };
    const scale = Math.min(cw / srcW, ch / srcH);
    const dw = srcW * scale, dh = srcH * scale;
    return { dx: (cw - dw) / 2, dy: (ch - dh) / 2, dw, dh };
  }
  function overlayRect(cw, ch, srcW, srcH, aspect, position, edges) {
    const { dx, dy, dw, dh } = displayedRect(cw, ch, srcW, srcH);
    const n = normCrop(srcW, srcH, aspect, position, edges);
    return { left: dx + n.x * dw, top: dy + n.y * dh, width: n.w * dw, height: n.h * dh, axis: n.axis, cropped: n.cropped };
  }

  // src/ui/editor/Fold.tsx
  function load(id) {
    try {
      return localStorage.getItem(`imaglr-fold-${id}`) === "1";
    } catch {
      return false;
    }
  }
  function save(id, open) {
    try {
      localStorage.setItem(`imaglr-fold-${id}`, open ? "1" : "0");
    } catch {
    }
  }
  function Fold({ id, label, summary, tone = "muted", children }) {
    const { Button, Collapse } = PluginApi.libraries.Bootstrap;
    const [open, setOpen] = react_default.useState(() => load(id));
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-fold" }, /* @__PURE__ */ react_default.createElement(
      Button,
      {
        variant: "link",
        className: "p-0 imaglr-touch",
        "aria-expanded": open,
        "aria-controls": `imaglr-fold-${id}`,
        onClick: () => {
          setOpen(!open);
          save(id, !open);
        }
      },
      open ? "\u25BE" : "\u25B8",
      " ",
      /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-fold-label" }, label),
      !open && summary ? /* @__PURE__ */ react_default.createElement("span", { className: tone === "warning" ? "text-warning" : "text-muted" }, " \xB7 ", summary) : null
    ), /* @__PURE__ */ react_default.createElement(Collapse, { in: open }, /* @__PURE__ */ react_default.createElement("div", { id: `imaglr-fold-${id}` }, children)));
  }

  // src/ui/editor/CropControls.tsx
  var LABELS = { top: "Top", bottom: "Bottom", left: "Left", right: "Right" };
  function CropControls({ crop, disabled, itemId, onChange, flip, onFlip }) {
    const { Button, ButtonGroup, Form } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [detecting, setDetecting] = react_default.useState(false);
    const edges = crop.edges ?? emptyEdges();
    const percent = (name) => Math.round((edges[name] ?? 0) * 100);
    function setEdge(name, value) {
      const v = Math.min(MAX_EDGE_PERCENT, Math.max(0, Math.round(Number.isFinite(value) ? value : 0))) / 100;
      onChange({ ...crop, edges: { ...edges, [name]: v } });
    }
    async function detect() {
      setDetecting(true);
      try {
        const r = await runOperation("crop_detect", { item_id: itemId });
        if (!hasEdges(r.edges)) Toast.success("No borders found.");
        onChange({ ...crop, edges: hasEdges(r.edges) ? r.edges : null });
      } catch (e) {
        Toast.error(e);
      } finally {
        setDetecting(false);
      }
    }
    const summary = [cropSummary(crop), flip ? "flipped" : ""].filter(Boolean).join(" \xB7 ");
    return /* @__PURE__ */ react_default.createElement(Fold, { id: "picture", label: "Picture options", summary }, /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, { className: "sr-only" }, "Aspect"), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, Object.keys(ASPECTS).map((a) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: a,
        variant: crop.aspect === a ? "primary" : "secondary",
        disabled,
        onClick: () => onChange({ ...crop, aspect: a })
      },
      a === "original" ? "Original" : a
    )))), crop.aspect !== "original" ? /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        type: "range",
        min: 0,
        max: 1,
        step: 0.01,
        value: crop.position,
        disabled,
        "aria-label": "Crop position",
        className: "mt-2",
        onChange: (e) => onChange({ ...crop, position: Number(e.target.value) })
      }
    ) : null, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-edges-header" }, /* @__PURE__ */ react_default.createElement("span", { className: "text-muted small" }, "Trim edges (%)"), /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-edges-actions" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "link", size: "sm", className: "p-0 imaglr-touch", disabled: disabled || detecting, onClick: detect }, detecting ? "Looking for borders\u2026" : "Detect borders"), hasEdges(edges) ? /* @__PURE__ */ react_default.createElement(
      Button,
      {
        variant: "link",
        size: "sm",
        className: "p-0 imaglr-touch",
        disabled,
        onClick: () => onChange({ ...crop, edges: null })
      },
      "Reset"
    ) : null)), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-edges" }, EDGE_NAMES.map((name) => /* @__PURE__ */ react_default.createElement("div", { key: name, className: "imaglr-edge" }, /* @__PURE__ */ react_default.createElement(Form.Label, { className: "imaglr-edge-label", htmlFor: `imaglr-edge-${name}` }, LABELS[name]), /* @__PURE__ */ react_default.createElement(
      Button,
      {
        variant: "secondary",
        disabled: disabled || percent(name) <= 0,
        "aria-label": `${LABELS[name]}: trim less`,
        onClick: () => setEdge(name, percent(name) - 1)
      },
      "\u2212"
    ), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        id: `imaglr-edge-${name}`,
        className: "text-input imaglr-edge-input",
        type: "number",
        inputMode: "numeric",
        min: 0,
        max: MAX_EDGE_PERCENT,
        step: 1,
        value: percent(name),
        disabled,
        onChange: (e) => setEdge(name, Number(e.target.value))
      }
    ), /* @__PURE__ */ react_default.createElement(
      Button,
      {
        variant: "secondary",
        disabled: disabled || percent(name) >= MAX_EDGE_PERCENT,
        "aria-label": `${LABELS[name]}: trim more`,
        onClick: () => setEdge(name, percent(name) + 1)
      },
      "+"
    )))), onFlip ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(
      Form.Check,
      {
        id: "imaglr-flip",
        type: "switch",
        label: "Flip horizontally",
        className: "mt-2",
        checked: !!flip,
        disabled,
        onChange: (e) => onFlip(e.target.checked)
      }
    ), flip ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted" }, "The sent clip is mirrored left-to-right; the preview above isn't.") : null) : null));
  }

  // src/ui/lib/send.ts
  var ACTION_LABELS = {
    draft: "Draft",
    queue: "Queued",
    publish: "Published"
  };
  var SENT_AS_LABELS = ACTION_LABELS;
  function pickBlog(blogs, blogId) {
    if (blogId != null) return blogs.find((b) => b.id === blogId) ?? null;
    return blogs.length === 1 ? blogs[0] : null;
  }
  function effectiveAction(blog, action) {
    return action ?? blog?.default_action ?? "draft";
  }
  function sendButtonLabel(action, blog) {
    if (!blog) return "Choose a blog";
    const name = blog.name ?? blog.label;
    if (action === "publish") return `Publish now on ${name}`;
    if (action === "queue") return `Add to ${name}'s queue`;
    return `Save draft to ${name}`;
  }
  function blogProblem(blog) {
    if (blog.paused_reason === "premium_required" || blog.supporter === false) {
      return "imaglr's API needs a paid supporter account.";
    }
    if (blog.paused_reason === "account_suspended") return "imaglr has suspended this account.";
    if (!blog.ok && blog.error_code) return blog.error_detail || blog.error_code;
    return null;
  }
  function imaglrLink(sentAs, postUrl) {
    if (sentAs === "draft" || !postUrl) return "https://imaglr.com/drafts";
    return postUrl;
  }
  function stashLink(f) {
    if (f.stash_image_id) return `/images/${f.stash_image_id}`;
    if (f.stash_scene_id) return `/scenes/${f.stash_scene_id}${f.in_s ? `?t=${Math.floor(f.in_s)}` : ""}`;
    return null;
  }

  // src/ui/model.ts
  var STATUS_LABELS = {
    pending: "New",
    exporting: "Preparing",
    ready: "Ready",
    sending: "Sending",
    sent: "Sent",
    failed: "Failed"
  };
  var STATUS_VARIANTS = {
    pending: "secondary",
    exporting: "info",
    ready: "success",
    sending: "info",
    sent: "primary",
    failed: "danger"
  };

  // src/ui/lib/clip.ts
  var DIRECT_CODECS = { h264: "avc1.42E01E", vp8: "vp8", vp9: "vp9", av1: "av01.0.05M.08", hevc: "hvc1" };
  var CONTAINER_MIME = { mp4: "video/mp4", m4v: "video/mp4", mov: "video/mp4", webm: "video/webm" };
  function directMime(info) {
    const container = CONTAINER_MIME[(info.format ?? "").toLowerCase()];
    const codec = DIRECT_CODECS[(info.video_codec ?? "").toLowerCase()];
    return container && codec ? `${container}; codecs="${codec}"` : null;
  }
  function pickStream(direct, streams, info, canPlay) {
    const mime = directMime(info);
    if (mime && canPlay(mime)) return direct;
    const mp4 = streams.find((s) => (s.mime_type ?? "").startsWith("video/mp4") && !/direct/i.test(s.label ?? ""));
    return mp4?.url ?? direct;
  }
  function sameOrigin(url, origin) {
    const u = new URL(url, origin);
    return origin + u.pathname + u.search;
  }
  var MIN_CLIP = 0.1;
  function clampTrim(inS, outS, duration, moved) {
    const max = duration && duration > 0 ? duration : Number.POSITIVE_INFINITY;
    let a = Math.max(0, Math.min(inS, max));
    let b = Math.max(0, Math.min(outS, max));
    if (b - a < MIN_CLIP) {
      if (moved === "in") a = Math.max(0, b - MIN_CLIP);
      else b = Math.min(max, a + MIN_CLIP);
    }
    return { inS: Math.round(a * 1e3) / 1e3, outS: Math.round(b * 1e3) / 1e3 };
  }

  // src/ui/lib/gif.ts
  var LONG_GIF_SECONDS = 15;
  var MB_PER_SECOND = { low: 1.2, high: 3 };
  var GIF_CROSSFADE_FACTOR = 1.2;
  var WEBP_FACTOR = 0.35;
  var GIF_FEED_WIDTH = 698;
  var GIF_SIZE_OPTIONS = [
    { label: "Original", value: null },
    { label: "480 px", value: 480 },
    { label: "320 px", value: 320 }
  ];
  function gifSizeChoicesFor(sourceWidth) {
    return GIF_SIZE_OPTIONS.filter((o) => o.value === null || !sourceWidth || o.value < sourceWidth);
  }
  var LADDER_FPS = 15;
  function fpsChoicesFor(sourceFps) {
    const out = [{ label: "Auto", value: null }];
    if (!sourceFps || sourceFps <= 0) return out;
    const source = Math.min(60, Math.round(sourceFps));
    const steps = [source, 30, 24, 15, 10].filter((f, i, a) => f <= source && f >= 5 && a.indexOf(f) === i);
    for (const f of steps) out.push({ label: f === source ? `${f} fps (source)` : `${f} fps`, value: f });
    return out;
  }
  function widthFactor(width) {
    const w = Math.min(width ?? GIF_FEED_WIDTH, GIF_FEED_WIDTH);
    return w * w / (GIF_FEED_WIDTH * GIF_FEED_WIDTH);
  }
  function crossfadeSeconds(seconds, fps = LADDER_FPS) {
    const x = Math.min(1, Math.max(0.5, seconds / 6));
    const total = Math.round(seconds * fps);
    const frames = Math.max(1, Math.min(Math.round(x * fps), Math.max(1, Math.floor(total / 3))));
    return frames / fps;
  }
  function gifSeconds(seconds, loop = "forward", fps = null) {
    const s = Math.max(0, seconds);
    if (loop === "boomerang") return s * 2;
    if (loop === "crossfade") return Math.max(0, s - crossfadeSeconds(s, fps ?? LADDER_FPS));
    return s;
  }
  function estimateGifMb(seconds, loop = "forward", width = null, format = "gif", fps = null) {
    const s = gifSeconds(seconds, loop, fps) * widthFactor(width) * (format === "webp" ? WEBP_FACTOR : 1) * ((fps ?? LADDER_FPS) / LADDER_FPS) * (loop === "crossfade" && format === "gif" ? GIF_CROSSFADE_FACTOR : 1);
    return [s * MB_PER_SECOND.low, s * MB_PER_SECOND.high];
  }
  function roundMb(n) {
    return n < 10 ? Math.round(n) : Math.round(n / 5) * 5;
  }
  function describeGifEstimate(seconds, loop = "forward", width = null, format = "gif", fps = null) {
    const [lo, hi] = estimateGifMb(seconds, loop, width, format, fps).map(roundMb);
    return lo === hi ? `roughly ${lo} MB` : `roughly ${lo}\u2013${hi} MB`;
  }

  // src/ui/lib/format.ts
  function fmtTime(s, decimals = 1) {
    if (s == null || !isFinite(s)) return "\u2013";
    const sign = s < 0 ? "-" : "";
    s = Math.abs(s);
    const h = Math.floor(s / 3600);
    const m = Math.floor(s % 3600 / 60);
    const sec = s % 60;
    const secStr = sec.toFixed(decimals).padStart(decimals ? 3 + decimals : 2, "0");
    return h ? `${sign}${h}:${String(m).padStart(2, "0")}:${secStr}` : `${sign}${m}:${secStr}`;
  }
  function parseTime(text) {
    const t = text.trim();
    if (!t) return null;
    const parts2 = t.split(":").map((p) => p.trim());
    if (parts2.some((p) => p === "" || !/^\d*\.?\d*$/.test(p))) return null;
    let total = 0;
    for (const p of parts2) total = total * 60 + parseFloat(p || "0");
    return isFinite(total) ? total : null;
  }
  function fmtDims(w, h) {
    return w && h ? `${w}\xD7${h}` : "\u2013";
  }
  function fmtDate(iso) {
    if (!iso) return "\u2013";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString(void 0, { dateStyle: "medium", timeStyle: "short" });
  }

  // src/ui/editor/ClipPanel.tsx
  var SCENE_PLAYBACK = `query($id: ID!) { findScene(id: $id) {
  paths { stream screenshot } sceneStreams { url mime_type label }
  files { video_codec format width height duration } } }`;
  var IMAGE_PLAYBACK = `query($id: ID!) { findImage(id: $id) {
  paths { image thumbnail }
  visual_files { ... on VideoFile { video_codec format width height duration } } } }`;
  async function loadPlayback(sceneId, imageId) {
    const canPlay = (mime) => document.createElement("video").canPlayType(mime) !== "";
    const origin = window.location.origin;
    if (sceneId) {
      const { findScene: s } = await gql(SCENE_PLAYBACK, { id: sceneId });
      const file = s.files[0] ?? {};
      return {
        url: sameOrigin(pickStream(s.paths.stream, s.sceneStreams, file, canPlay), origin),
        poster: s.paths.screenshot ? sameOrigin(s.paths.screenshot, origin) : null,
        duration: file.duration ?? null
      };
    }
    const { findImage: i } = await gql(IMAGE_PLAYBACK, { id: imageId });
    return {
      url: sameOrigin(i.paths.image, origin),
      poster: i.paths.thumbnail ? sameOrigin(i.paths.thumbnail, origin) : null,
      duration: i.visual_files[0]?.duration ?? null
    };
  }
  var FORMAT_LABELS = { video: "Video", webp: "WebP", gif: "GIF" };
  var COVER_HOLD_SECONDS = 1.5;
  var FORMAT_HINTS = {
    video: "Best quality, keeps the sound, and the smallest file for anything long. The viewer has to click play.",
    gif: "Plays automatically in the feed. No sound, limited to 256 colours, and the largest file of the three, so short clips only.",
    webp: "Plays automatically in the feed. Full colour and a third to a half of a GIF's size, so it loads faster and can be longer. No sound."
  };
  var LOOP_LABELS = { forward: "Forward", boomerang: "Boomerang", crossfade: "Crossfade" };
  var LOOP_HINTS = {
    forward: "Plays the clip through, then starts again from In. Find a seamless loop looks for In and Out points near yours where the join hides.",
    boomerang: "A boomerang plays the clip forward then backward, so it loops without a jump. It doubles the frames.",
    crossfade: "Dissolves the last moment into the first, so footage that never repeats still loops without a jump."
  };
  var SEARCH_LABELS = { near: "Near In and Out", from_in: "From In" };
  var JOIN_LEAD_SECONDS = 1.5;
  function delta(seconds) {
    const r = Math.round(seconds * 10) / 10;
    return r === 0 ? "\xB10 s" : `${r > 0 ? "+" : "\u2212"}${Math.abs(r).toFixed(1)} s`;
  }
  function TimeRow({ label, value, disabled, onSet, onNudge, onType }) {
    const { Button, Form } = PluginApi.libraries.Bootstrap;
    const [text, setText] = react_default.useState(fmtTime(value));
    react_default.useEffect(() => setText(fmtTime(value)), [value]);
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-time-row" }, /* @__PURE__ */ react_default.createElement(Form.Label, { className: "imaglr-time-label" }, label), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        className: "text-input imaglr-time-input",
        value: text,
        disabled,
        "aria-label": `${label} time`,
        onChange: (e) => setText(e.target.value),
        onBlur: () => {
          const t = parseTime(text);
          if (t === null) setText(fmtTime(value));
          else onType(t);
        }
      }
    ), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-time-buttons" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled, onClick: () => onNudge(-1), "aria-label": `${label} back 1 second` }, "\u22121s"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled, onClick: () => onNudge(-0.1), "aria-label": `${label} back a tenth` }, "\u22120.1"), /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", disabled, onClick: onSet }, "Set here"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled, onClick: () => onNudge(0.1), "aria-label": `${label} forward a tenth` }, "+0.1"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled, onClick: () => onNudge(1), "aria-label": `${label} forward 1 second` }, "+1s")));
  }
  function formatHeader(v, estimate, edge) {
    if (v.format !== "video") {
      const loop = v.loop === "boomerang" || v.loop === "crossfade" ? ` \xB7 ${v.loop}` : "";
      const size = v.gifWidth ? ` \xB7 ${v.gifWidth} px` : "";
      const fps = v.gifFps ? ` \xB7 ${v.gifFps} fps` : "";
      return {
        text: `${FORMAT_LABELS[v.format]}${loop}${size}${fps} \xB7 ${describeGifEstimate(v.outS - v.inS, v.loop, v.gifWidth, v.format, v.gifFps)}`,
        warn: gifSeconds(v.outS - v.inS, v.loop) > LONG_GIF_SECONDS
      };
    }
    const parts2 = [
      "Video",
      CODEC_LABELS[v.codec],
      edgeLabel(edge),
      v.mute ? "no sound" : "",
      v.coverT !== null ? `cover at ${fmtTime(v.coverT)}` : "",
      estimate.short
    ];
    return { text: parts2.filter(Boolean).join(" \xB7 "), warn: estimate.warn };
  }
  function ClipPanel({ itemId, sceneId, imageId, value, disabled, gifTargetMb, sourceFps, gifPreview, makingGif, onChange, onSaveStill, onPreviewGif }) {
    const { Button, ButtonGroup, Form } = PluginApi.libraries.Bootstrap;
    const video = react_default.useRef(null);
    const box = react_default.useRef(null);
    const [playback, setPlayback] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    const [looping, setLooping] = react_default.useState(false);
    const [size, setSize] = react_default.useState({ w: 0, h: 0, vw: 0, vh: 0 });
    const [showGif, setShowGif] = react_default.useState(true);
    const Toast = PluginApi.hooks.useToast();
    const [searchMode, setSearchMode] = react_default.useState("near");
    const [finding, setFinding] = react_default.useState(false);
    const [found, setFound] = react_default.useState(null);
    const valueRef = react_default.useRef(value);
    valueRef.current = value;
    const cropKey = JSON.stringify(value.crop) + (value.flip ? "|flip" : "");
    react_default.useEffect(() => {
      setFound(null);
    }, [cropKey]);
    react_default.useEffect(() => {
      setFound((f) => f && !f.candidates.some((c) => Math.abs(c.in_s - value.inS) < 2e-3 && Math.abs(c.out_s - value.outS) < 2e-3) ? null : f);
    }, [value.inS, value.outS]);
    react_default.useEffect(() => {
      const v = video.current;
      if (!looping || !v || !v.requestVideoFrameCallback || !v.cancelVideoFrameCallback) return;
      let handle = 0;
      const check = () => {
        const cur = valueRef.current;
        if (v.currentTime >= cur.outS) v.currentTime = cur.inS;
        handle = v.requestVideoFrameCallback(check);
      };
      handle = v.requestVideoFrameCallback(check);
      return () => v.cancelVideoFrameCallback(handle);
    }, [looping]);
    react_default.useEffect(() => {
      loadPlayback(sceneId, imageId).then(setPlayback, (e) => setError(e.message));
    }, [sceneId, imageId]);
    react_default.useEffect(() => {
      const onResize = () => measure();
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }, []);
    function measure() {
      const v = video.current;
      const b = box.current;
      if (v && b) setSize({ w: b.clientWidth, h: b.clientHeight, vw: v.videoWidth, vh: v.videoHeight });
    }
    const duration = playback?.duration ?? null;
    const now = () => video.current?.currentTime ?? 0;
    function trim(inS, outS, moved) {
      const t = clampTrim(inS, outS, duration, moved);
      onChange({ ...value, inS: t.inS, outS: t.outS });
      if (video.current) video.current.currentTime = moved === "in" ? t.inS : Math.max(t.inS, t.outS - 1);
    }
    function playClip() {
      const v = video.current;
      if (!v) return;
      v.currentTime = value.inS;
      setLooping(true);
      v.play().catch(() => void 0);
    }
    function playJoin(inS = value.inS, outS = value.outS) {
      const v = video.current;
      if (!v) return;
      setShowGif(false);
      v.currentTime = Math.max(inS, outS - JOIN_LEAD_SECONDS);
      setLooping(true);
      v.play().catch(() => void 0);
    }
    async function findLoops() {
      setFinding(true);
      try {
        const r = await runOperation("loop_find", { item_id: itemId, search: searchMode });
        setFound({ inS: value.inS, outS: value.outS, candidates: r.candidates });
      } catch (e) {
        Toast.error(e);
      } finally {
        setFinding(false);
      }
    }
    function pickLoop(c) {
      const t = clampTrim(c.in_s, c.out_s, duration, "out");
      onChange({ ...value, inS: t.inS, outS: t.outS });
      playJoin(t.inS, t.outS);
    }
    const sourceEdge = Math.max(size.vw, size.vh) || null;
    const sizeChoices = sizeChoicesFor(sourceEdge);
    const gifSizeChoices = gifSizeChoicesFor(size.vw || null);
    const fpsChoices = fpsChoicesFor(sourceFps);
    const estimate = videoEstimate(value.outS - value.inS, value.codec, outputEdge(sourceEdge, value.maxEdge), value.mute);
    const header = formatHeader(value, estimate, outputEdge(sourceEdge, value.maxEdge));
    const rect = overlayRect(size.w, size.h, size.vw, size.vh, value.crop.aspect, value.crop.position, value.crop.edges);
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-clip" }, error ? /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-danger" }, "Can't play this video: ", error) : null, /* @__PURE__ */ react_default.createElement("div", { ref: box, className: "imaglr-preview imaglr-video" }, gifPreview && showGif ? /* @__PURE__ */ react_default.createElement("img", { className: "imaglr-gif-preview", src: baseUrl() + gifPreview.url, alt: "The GIF as it will be sent" }) : null, playback ? /* @__PURE__ */ react_default.createElement(
      "video",
      {
        ref: video,
        src: playback.url,
        poster: playback.poster ?? void 0,
        playsInline: true,
        controls: true,
        preload: "metadata",
        muted: value.mute,
        style: gifPreview && showGif ? { display: "none" } : void 0,
        onLoadedMetadata: () => {
          if (video.current) video.current.currentTime = value.inS;
          measure();
        },
        onTimeUpdate: () => {
          const v = video.current;
          if (v && looping && v.currentTime >= valueRef.current.outS) v.currentTime = valueRef.current.inS;
        },
        onPause: () => setLooping(false)
      }
    ) : null, rect.cropped && !(gifPreview && showGif) ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-crop", style: { left: rect.left, top: rect.top, width: rect.width, height: rect.height } }) : null), value.format !== "video" ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-gif-bar" }, gifPreview ? /* @__PURE__ */ react_default.createElement("span", { className: "small text-muted" }, "This is the ", FORMAT_LABELS[value.format], " that will be sent: ", gifPreview.note) : /* @__PURE__ */ react_default.createElement("span", { className: "small text-muted" }, "Make the ", FORMAT_LABELS[value.format], " now to see exactly what will be sent."), /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-clip-actions" }, gifPreview ? /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => setShowGif(!showGif) }, showGif ? "Show video" : `Show ${FORMAT_LABELS[value.format]}`) : null, /* @__PURE__ */ react_default.createElement(Button, { variant: gifPreview ? "secondary" : "primary", disabled: disabled || makingGif, onClick: onPreviewGif }, makingGif ? `Making the ${FORMAT_LABELS[value.format]}\u2026` : gifPreview ? "Make it again" : `Preview ${FORMAT_LABELS[value.format]}`))) : null, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-clip-summary" }, /* @__PURE__ */ react_default.createElement("span", null, fmtTime(value.inS), " \u2192 ", fmtTime(value.outS), " \xB7 ", /* @__PURE__ */ react_default.createElement("strong", null, (value.outS - value.inS).toFixed(1), " s")), /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-clip-actions" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: playClip }, "Play clip"), value.format !== "video" ? /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => playJoin() }, "Play the join") : null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled, onClick: () => onSaveStill(now()) }, "Save still"))), /* @__PURE__ */ react_default.createElement(
      TimeRow,
      {
        label: "In",
        value: value.inS,
        disabled,
        onSet: () => trim(now(), value.outS, "in"),
        onNudge: (d) => trim(value.inS + d, value.outS, "in"),
        onType: (t) => trim(t, value.outS, "in")
      }
    ), /* @__PURE__ */ react_default.createElement(
      TimeRow,
      {
        label: "Out",
        value: value.outS,
        disabled,
        onSet: () => trim(value.inS, now(), "out"),
        onNudge: (d) => trim(value.inS, value.outS + d, "out"),
        onType: (t) => trim(value.inS, t, "out")
      }
    ), /* @__PURE__ */ react_default.createElement(
      CropControls,
      {
        crop: value.crop,
        disabled,
        itemId,
        onChange: (crop) => onChange({ ...value, crop }),
        flip: value.flip,
        onFlip: (flip) => onChange({ ...value, flip })
      }
    ), /* @__PURE__ */ react_default.createElement(Fold, { id: "format", label: "Format options", summary: header.text, tone: header.warn ? "warning" : "muted" }, /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-2" }, /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, Object.keys(FORMAT_LABELS).map((f) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: f,
        variant: value.format === f ? "primary" : "secondary",
        disabled,
        onClick: () => onChange({ ...value, format: f })
      },
      FORMAT_LABELS[f]
    )))), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, FORMAT_HINTS[value.format])), value.format !== "video" ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-2 mb-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Loop"), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, Object.keys(LOOP_LABELS).map((l) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: l,
        variant: value.loop === l ? "primary" : "secondary",
        disabled,
        onClick: () => onChange({ ...value, loop: l })
      },
      LOOP_LABELS[l]
    )))), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, LOOP_HINTS[value.loop]), value.loop === "forward" ? /* @__PURE__ */ react_default.createElement("div", { className: "mt-2" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-cover-row" }, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, Object.keys(SEARCH_LABELS).map((m) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: m,
        variant: searchMode === m ? "primary" : "secondary",
        disabled: disabled || finding,
        onClick: () => setSearchMode(m)
      },
      SEARCH_LABELS[m]
    ))), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled: disabled || finding, onClick: findLoops }, finding ? "Looking\u2026" : "Find a seamless loop")), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, searchMode === "near" ? "Looks within 2 s of your In and Out for a pair where the frames match across the join." : "Keeps In close and tries every Out from a second later up to yours; between equally clean joins the shorter loop wins.", " ", "Nothing changes until you tap a result."), found ? found.candidates.length ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-loop-candidates mt-2" }, found.candidates.map((c) => {
      const current = Math.abs(c.in_s - value.inS) < 2e-3 && Math.abs(c.out_s - value.outS) < 2e-3;
      return /* @__PURE__ */ react_default.createElement(Button, { key: `${c.in_s}-${c.out_s}`, variant: current ? "primary" : "secondary", disabled, onClick: () => pickLoop(c) }, (c.out_s - c.in_s).toFixed(1), " s \xB7 In ", delta(c.in_s - found.inS), " \xB7 Out ", delta(c.out_s - found.outS), " \xB7 ", c.quality);
    })) : /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-2" }, "No loop found near these points. Try From In, or the Crossfade loop.") : null) : null), gifSizeChoices.length > 1 ? /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mb-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Picture size"), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, gifSizeChoices.map((o) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: o.label,
        variant: (value.gifWidth ?? null) === o.value ? "primary" : "secondary",
        disabled,
        onClick: () => onChange({ ...value, gifWidth: o.value })
      },
      o.label
    )))), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, "Original is the feed's width, 698 px. A smaller picture makes a much smaller file.")) : null, fpsChoices.length > 1 ? /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mb-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Frame rate"), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, fpsChoices.map((o) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: o.label,
        variant: (value.gifFps ?? null) === o.value ? "primary" : "secondary",
        disabled,
        onClick: () => onChange({ ...value, gifFps: o.value })
      },
      o.label
    )))), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, "Auto starts at 15 fps and drops lower only if the file is too big. A higher rate is smoother and makes a proportionally bigger file; it can't go above the source's own rate.")) : null, /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, "This will be a ", FORMAT_LABELS[value.format], " of ", describeGifEstimate(value.outS - value.inS, value.loop, value.gifWidth, value.format, value.gifFps), ". Files over about ", gifTargetMb, " MB are slow to load, so the plugin will automatically lower the quality if it has to."), gifSeconds(value.outS - value.inS, value.loop) > LONG_GIF_SECONDS ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-warning mt-1" }, "Long ", FORMAT_LABELS[value.format], "s may need lower frame-rates and resolutions. ", value.loop === "boomerang" ? "A boomerang plays twice as long, so clips" : "Clips", " below ", value.loop === "boomerang" ? LONG_GIF_SECONDS / 2 : LONG_GIF_SECONDS, " seconds work best.") : null) : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-2 mb-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Codec"), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, Object.keys(CODEC_LABELS).map((c) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: c,
        variant: value.codec === c ? "primary" : "secondary",
        disabled,
        onClick: () => onChange({ ...value, codec: c })
      },
      CODEC_LABELS[c]
    )))), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, "H.265 files are 40 % smaller than H.264 at the same quality, so a longer clip fits the upload limit, at the cost of a slower encode.")), sizeChoices.length > 1 ? /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mb-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Picture size"), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, sizeChoices.map((o) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: o.label,
        variant: (value.maxEdge ?? null) === o.value ? "primary" : "secondary",
        disabled,
        onClick: () => onChange({ ...value, maxEdge: o.value })
      },
      o.label
    )))), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, "Smaller pictures make smaller files and encode faster. Original keeps the source's size, up to 1080p.")) : null, /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-2 mb-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Estimated size"), /* @__PURE__ */ react_default.createElement("div", { className: `small ${estimate.warn ? "text-warning" : "text-muted"}` }, estimate.text)), /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-2 mb-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Cover"), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mb-2" }, "The video cover is shown before the video is played. To set a cover, scan to the frame you want in the player, then press the button below."), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-cover-row" }, value.coverT === null ? /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled, onClick: () => onChange({ ...value, coverT: Math.round(now() * 1e3) / 1e3 }) }, "Use this frame as the cover") : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("span", null, "The frame at ", /* @__PURE__ */ react_default.createElement("strong", null, fmtTime(value.coverT)), ", shown for ", COVER_HOLD_SECONDS, " s before the clip"), /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-clip-actions" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => {
      if (video.current) {
        video.current.pause();
        video.current.currentTime = value.coverT ?? 0;
      }
    } }, "Show"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled, onClick: () => onChange({ ...value, coverT: Math.round(now() * 1e3) / 1e3 }) }, "Use this frame"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled, onClick: () => onChange({ ...value, coverT: null }) }, "Clear"))))), /* @__PURE__ */ react_default.createElement(
      Form.Check,
      {
        id: "imaglr-mute",
        type: "switch",
        label: "Remove sound",
        checked: value.mute,
        disabled,
        onChange: (e) => onChange({ ...value, mute: e.target.checked })
      }
    ))));
  }

  // src/ui/lib/tags.ts
  var MAX_TAGS = 30;
  var MAX_LEN = 64;
  function normalise(name, lowercase) {
    const s = name.trim().replace(/\s+/g, " ");
    return lowercase ? s.toLowerCase() : s;
  }
  function checkNewTag(tags, raw, lowercase) {
    const tag = normalise(raw, lowercase);
    if (!tag) return { ok: false, error: "Empty tag" };
    if (tag.length > MAX_LEN) return { ok: false, error: `Tags can be at most ${MAX_LEN} characters` };
    if (tags.some((t) => t.toLowerCase() === tag.toLowerCase())) return { ok: false, error: "Already added" };
    if (tags.length >= MAX_TAGS) return { ok: false, error: `imaglr allows ${MAX_TAGS} tags per post` };
    return { ok: true, tag };
  }
  function addOptionFirst(typed, suggestions) {
    const q = typed.toLowerCase();
    return !suggestions.some((s) => s.toLowerCase().startsWith(q));
  }
  function spareSuggestions(s, tags) {
    const taken = new Set(tags.map((t) => t.toLowerCase()));
    const all = [...s?.active ?? [], ...s?.greyed ?? []].filter((t) => !taken.has(t.tag.toLowerCase()));
    const unique = all.filter((t, i) => all.findIndex((o) => o.tag.toLowerCase() === t.tag.toLowerCase()) === i);
    return {
      addable: unique.filter((t) => t.reason !== "too_long").map((t) => t.tag),
      tooLong: unique.filter((t) => t.reason === "too_long").map((t) => t.original || t.tag)
    };
  }

  // src/ui/editor/TagField.tsx
  var STYLES = {
    option: (base) => ({ ...base, color: "#000" }),
    container: (base, state) => ({ ...base, zIndex: state.isFocused ? 10 : base.zIndex }),
    multiValueRemove: (base, state) => ({ ...base, color: state.isFocused ? base.color : "#333333" })
  };
  var toOption = (tag) => ({ value: tag, label: tag });
  function TagInput({ tags, extra = [], lowercase, disabled, inputId, placeholder, onChange, onMessage }) {
    const Select = PluginApi.libraries.ReactSelect.default;
    const [input, setInput] = react_default.useState("");
    const [found, setFound] = react_default.useState([]);
    react_default.useEffect(() => {
      const q2 = input.trim();
      if (!q2) {
        setFound([]);
        return;
      }
      const timer = window.setTimeout(() => {
        runOperation("tags_suggest", { q: q2 }).then((r) => setFound(r.tags), () => setFound([]));
      }, 200);
      return () => window.clearTimeout(timer);
    }, [input]);
    const taken = new Set(tags.map((t) => t.toLowerCase()));
    const q = input.trim().toLowerCase();
    const names = (q ? [...extra.filter((t) => t.toLowerCase().includes(q)), ...found] : extra).map((t) => normalise(t, lowercase));
    const options = names.filter((t, i) => !taken.has(t.toLowerCase()) && names.findIndex((o) => o.toLowerCase() === t.toLowerCase()) === i).map(toOption);
    const typed = checkNewTag(tags, input, lowercase);
    if (input.trim() && typed.ok && !options.some((o) => o.value.toLowerCase() === typed.tag.toLowerCase())) {
      const add = { value: typed.tag, label: `Add "${typed.tag}"`, isNew: true };
      if (addOptionFirst(typed.tag, options.map((o) => o.value))) options.unshift(add);
      else options.push(add);
    }
    function change(selected) {
      const next = (selected ?? []).map((o) => o.value);
      if (next.length > MAX_TAGS) {
        onMessage?.(`imaglr allows ${MAX_TAGS} tags per post. Remove one first.`);
        return;
      }
      onMessage?.(null);
      setInput("");
      onChange(next);
    }
    return /* @__PURE__ */ react_default.createElement(
      Select,
      {
        inputId,
        className: "react-select tag-select imaglr-tag-select",
        classNamePrefix: "react-select",
        isMulti: true,
        isClearable: true,
        isDisabled: disabled,
        closeMenuOnSelect: false,
        value: tags.map(toOption),
        options,
        inputValue: input,
        onInputChange: (value, meta) => {
          if (meta.action === "input-change") {
            setInput(value);
            onMessage?.(null);
          }
        },
        onChange: change,
        filterOption: () => true,
        placeholder: placeholder ?? "Add tags\u2026",
        noOptionsMessage: () => input.trim() && !typed.ok ? typed.error : null,
        styles: STYLES,
        components: { IndicatorSeparator: () => null }
      }
    );
  }
  function TagField({ tags, suggestions, lowercase, disabled, auto, onChange, onReset }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const [message, setMessage] = react_default.useState(null);
    const spare = spareSuggestions(suggestions, tags);
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-tags" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-tags-header" }, /* @__PURE__ */ react_default.createElement("label", { htmlFor: "imaglr-tag-field" }, /* @__PURE__ */ react_default.createElement("strong", null, "imaglr tags")), /* @__PURE__ */ react_default.createElement("span", { className: tags.length >= MAX_TAGS ? "text-warning" : "text-muted" }, tags.length, " / ", MAX_TAGS)), auto === void 0 ? null : auto ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mb-1" }, "From the Stash tags and your tag rules; they keep up with changes until you edit them.") : /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mb-1" }, "Edited by you.", " ", onReset ? /* @__PURE__ */ react_default.createElement(Button, { variant: "link", size: "sm", className: "p-0 align-baseline imaglr-touch", disabled, onClick: onReset }, "Use the suggested tags again") : null), /* @__PURE__ */ react_default.createElement(
      TagInput,
      {
        inputId: "imaglr-tag-field",
        tags,
        extra: spare.addable,
        lowercase,
        disabled,
        onChange,
        onMessage: setMessage
      }
    ), message ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-warning mt-1" }, message) : null, spare.tooLong.length ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted mt-1" }, "Not usable on imaglr (over 64 characters): ", spare.tooLong.join(", ")) : null);
  }

  // src/ui/editor/Editor.tsx
  var BUSY = ["exporting", "sending"];
  function CropPreview({ file, crop }) {
    const box = react_default.useRef(null);
    const [size, setSize] = react_default.useState({ w: 0, h: 0, sw: file.width ?? 0, sh: file.height ?? 0 });
    function measure(img) {
      const el = box.current;
      if (!el) return;
      setSize((s) => ({
        w: el.clientWidth,
        h: el.clientHeight,
        sw: img?.naturalWidth || s.sw,
        sh: img?.naturalHeight || s.sh
      }));
    }
    react_default.useEffect(() => {
      const onResize = () => measure();
      onResize();
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }, []);
    const rect = overlayRect(size.w, size.h, size.sw, size.sh, crop.aspect, crop.position, crop.edges);
    const src = file.image ?? file.thumb;
    return /* @__PURE__ */ react_default.createElement("div", { ref: box, className: "imaglr-preview" }, src ? /* @__PURE__ */ react_default.createElement("img", { src: baseUrl() + src, alt: "", onLoad: (e) => measure(e.currentTarget) }) : null, rect.cropped ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-crop", style: { left: rect.left, top: rect.top, width: rect.width, height: rect.height } }) : null);
  }
  function FileStrip({ files, disabled, onArrange }) {
    const { Link } = PluginApi.libraries.ReactRouterDOM;
    const ids = files.map((f) => f.id);
    const move = (from, to) => {
      const next = [...ids];
      next.splice(to, 0, next.splice(from, 1)[0]);
      onArrange(next);
    };
    return /* @__PURE__ */ react_default.createElement("ol", { className: "imaglr-strip" }, files.map((f, n) => /* @__PURE__ */ react_default.createElement("li", { key: f.id, className: "imaglr-strip-item", title: f.title }, stashLink(f) ? /* @__PURE__ */ react_default.createElement(Link, { to: stashLink(f), title: `${f.title} in Stash` }, f.thumb ? /* @__PURE__ */ react_default.createElement("img", { src: baseUrl() + f.thumb, alt: "" }) : null) : f.thumb ? /* @__PURE__ */ react_default.createElement("img", { src: baseUrl() + f.thumb, alt: "" }) : null, /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-strip-number" }, n + 1), disabled ? null : /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-strip-actions" }, /* @__PURE__ */ react_default.createElement("button", { type: "button", "aria-label": "Move earlier", disabled: n === 0, onClick: () => move(n, n - 1) }, "\u25C0"), /* @__PURE__ */ react_default.createElement("button", { type: "button", "aria-label": "Remove from this post", onClick: () => onArrange(ids.filter((i) => i !== f.id)) }, "\xD7"), /* @__PURE__ */ react_default.createElement("button", { type: "button", "aria-label": "Move later", disabled: n === files.length - 1, onClick: () => move(n, n + 1) }, "\u25B6")))));
  }
  function Editor({ itemId, onClose }) {
    const { Modal, Button, Form, ButtonGroup, Alert, ProgressBar } = PluginApi.libraries.Bootstrap;
    const { Link } = PluginApi.libraries.ReactRouterDOM;
    const Toast = PluginApi.hooks.useToast();
    const [detail, setDetail] = react_default.useState(null);
    const [tags, setTags] = react_default.useState([]);
    const [caption, setCaption] = react_default.useState("");
    const [crop, setCrop] = react_default.useState({ aspect: "original", position: 0.5 });
    const [trim, setTrim] = react_default.useState(
      { inS: 0, outS: 0, mute: false, flip: false, format: "video", codec: "h264", maxEdge: null, loop: "forward", gifWidth: null, gifFps: null, coverT: null }
    );
    const [blogId, setBlogId] = react_default.useState(null);
    const [action, setAction] = react_default.useState(null);
    const [confirmPublish, setConfirmPublish] = react_default.useState(false);
    const [confirmRemove, setConfirmRemove] = react_default.useState(false);
    const [confirmReblog, setConfirmReblog] = react_default.useState(false);
    const [tagsAuto, setTagsAuto] = react_default.useState(true);
    const [resetTags, setResetTags] = react_default.useState(false);
    const [busy, setBusy] = react_default.useState(false);
    const [changed, setChanged] = react_default.useState(false);
    const [dirty, setDirty] = react_default.useState(false);
    const [makingGif, setMakingGif] = react_default.useState(false);
    const load2 = react_default.useCallback(() => {
      runOperation("item_detail", { item_id: itemId }).then((d) => {
        setDetail(d);
        setTags(d.item.tags);
        setTagsAuto(d.item.tags_auto);
        setResetTags(false);
        setCaption(d.item.caption);
        setCrop(d.item.crop);
        setTrim({
          inS: d.item.in_s ?? 0,
          outS: d.item.out_s ?? 0,
          mute: d.item.mute,
          flip: d.item.flip,
          format: d.item.format,
          codec: d.item.codec ?? "h264",
          maxEdge: d.item.max_edge ?? null,
          loop: d.item.loop ?? "forward",
          gifWidth: d.item.gif_width ?? null,
          gifFps: d.item.gif_fps ?? null,
          coverT: d.item.cover_t ?? null
        });
        setBlogId(d.item.blog_id);
        setAction(d.item.action);
        setDirty(false);
      }, (e) => {
        Toast.error(e);
        onClose(true);
      });
    }, [itemId]);
    react_default.useEffect(load2, [load2]);
    const busyStatus = detail ? BUSY.includes(detail.item.status) : false;
    react_default.useEffect(() => {
      if (!busyStatus) return;
      const timer = window.setInterval(load2, 2e3);
      return () => window.clearInterval(timer);
    }, [busyStatus, load2]);
    if (!detail) return null;
    const { item, files, blogs } = detail;
    const queueTag = detail.queue_tag;
    const locked = BUSY.includes(item.status) || busy;
    const blog = pickBlog(blogs, blogId);
    const sendAction = effectiveAction(blog, action);
    const problem = blog ? blogProblem(blog) : null;
    const fromImaglr = files.find((f) => f.saved_from)?.saved_from ?? null;
    const fromCreator = files.find((f) => f.saved_from)?.saved_creator ?? null;
    const single = files.length === 1 && item.kind !== "set";
    const isClip = item.kind === "clip";
    function edit(setter) {
      return (value) => {
        setter(value);
        setDirty(true);
      };
    }
    async function save2() {
      if (!dirty) return;
      await runOperation("item_update", {
        item_id: item.id,
        changes: {
          tags,
          caption,
          crop,
          blog_id: blogId,
          action,
          ...resetTags ? { tags_auto: true } : {},
          ...isClip ? {
            in_s: trim.inS,
            out_s: trim.outS,
            mute: trim.mute,
            flip: trim.flip,
            format: trim.format,
            codec: trim.codec,
            max_edge: trim.maxEdge,
            loop: trim.loop,
            gif_width: trim.gifWidth,
            gif_fps: trim.gifFps,
            cover_t: trim.coverT
          } : {}
        }
      });
      setDirty(false);
      setChanged(true);
    }
    function cancel() {
      onClose(changed);
    }
    async function saveAndClose() {
      setBusy(true);
      try {
        await save2();
        onClose(true);
      } catch (e) {
        Toast.error(e);
        setBusy(false);
      }
    }
    async function send() {
      if (sendAction === "publish" && !confirmPublish) {
        setConfirmPublish(true);
        return;
      }
      setBusy(true);
      try {
        await save2();
        await runOperation("send", { item_id: item.id, blog_id: blog?.id, action });
        onClose(true);
      } catch (e) {
        Toast.error(e);
        setBusy(false);
        setConfirmPublish(false);
      }
    }
    async function arrange(ids) {
      try {
        await save2();
        const result = await runOperation("post_arrange", { item_id: item.id, item_ids: ids });
        setChanged(true);
        if (result.post_id) load2();
        else onClose(true);
      } catch (e) {
        Toast.error(e);
      }
    }
    async function previewGif() {
      setMakingGif(true);
      try {
        await save2();
        await runOperation("gif_preview", { item_id: item.id });
        setChanged(true);
        load2();
      } catch (e) {
        Toast.error(e);
      } finally {
        setMakingGif(false);
      }
    }
    async function saveStill(t) {
      try {
        await runOperation("still_create", { item_id: item.id, t });
        setChanged(true);
        Toast.success(`Still saved at ${t.toFixed(1)} s. It's on the Images tab.`);
      } catch (e) {
        Toast.error(e);
      }
    }
    async function cancelSend() {
      await runOperation("cancel", { item_id: item.id }).catch((e) => Toast.error(e));
      onClose(true);
    }
    const removeLabel = item.kind === "still" ? "Delete still" : `Remove "${queueTag}" tag${item.kind === "set" ? "s" : ""}`;
    const removeQuestion = item.kind === "still" ? "Delete this still? It only exists in the plugin." : `Remove the "${queueTag}" tag in Stash${item.kind === "set" ? " from every file in this post" : ""}? It leaves this page. Nothing on imaglr is changed and nothing is deleted.`;
    async function reblog() {
      if (!blog || !fromImaglr) return;
      setBusy(true);
      try {
        await runOperation("reblog", { post_id: fromImaglr, blog_id: blog.id, caption, tags });
        Toast.success(`Reblogged to ${blog.label}.`);
        await runOperation("remove_from_queue", { item_id: item.id });
        onClose(true);
      } catch (e) {
        setConfirmReblog(false);
        setBusy(false);
        Toast.error(e);
      }
    }
    async function remove() {
      setBusy(true);
      try {
        await runOperation("remove_from_queue", { item_id: item.id });
        onClose(true);
      } catch (e) {
        setConfirmRemove(false);
        setBusy(false);
        Toast.error(e);
      }
    }
    const kindLabel = item.kind === "set" ? "Files" : item.kind === "clip" ? "Clip" : item.kind === "still" ? "Still" : "Image";
    const sourceLink = item.kind === "set" ? null : stashLink(files[0] ?? {});
    const itemName = item.kind === "set" ? `${files.length} files in one post` : sourceLink ? /* @__PURE__ */ react_default.createElement(Link, { to: sourceLink, title: item.kind === "clip" ? "Open the scene in Stash at this clip (its marker is on the Markers tab)" : "Open in Stash" }, item.source_title) : item.source_title;
    return (
      // Like Stash's own dialogs (ModalComponent): clicking outside or pressing Escape does nothing;
      // leave with Cancel or the send button.
      /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: () => void 0, keyboard: false, size: "lg", dialogClassName: "imaglr-editor", scrollable: true }, /* @__PURE__ */ react_default.createElement(Modal.Header, null, /* @__PURE__ */ react_default.createElement(Modal.Title, null, fromImaglr ? "Reblog on imaglr" : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, "Post to imaglr ", /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, STATUS_LABELS[item.status])))), /* @__PURE__ */ react_default.createElement(Modal.Body, null, /* @__PURE__ */ react_default.createElement("dl", { className: "row imaglr-item-facts" }, /* @__PURE__ */ react_default.createElement("dt", { className: "col-3 col-sm-2" }, kindLabel), /* @__PURE__ */ react_default.createElement("dd", { className: "col-9 col-sm-10" }, itemName)), item.error_detail && !BUSY.includes(item.status) ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "warning" }, item.error_detail) : null, BUSY.includes(item.status) ? /* @__PURE__ */ react_default.createElement("div", { className: "mb-3" }, /* @__PURE__ */ react_default.createElement(ProgressBar, { now: Math.round(item.progress * 100), label: STATUS_LABELS[item.status] })) : null, item.hdr_warning ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "info" }, "This video is HDR. Colours may look flatter on imaglr (HDR isn't converted).") : null, fromImaglr ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-reblog-source" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-reblog-thumbs" }, files.map((f) => f.thumb ? /* @__PURE__ */ react_default.createElement("img", { key: f.id, src: baseUrl() + f.thumb, alt: "" }) : null)), /* @__PURE__ */ react_default.createElement("p", { className: "mb-0" }, fromCreator ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, "A post by ", /* @__PURE__ */ react_default.createElement("strong", null, "@", fromCreator), ", saved from imaglr. ") : "Saved from imaglr. ", /* @__PURE__ */ react_default.createElement("a", { href: `https://imaglr.com/post/${fromImaglr}`, target: "_blank", rel: "noopener noreferrer" }, "View the post")), /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted mb-0" }, "A reblog shares the post as it was posted, credited to its creator, so the picture can't be edited here. Add your own caption and tags below.")) : isClip ? /* @__PURE__ */ react_default.createElement(
        ClipPanel,
        {
          itemId: item.id,
          sceneId: files[0].stash_scene_id,
          imageId: files[0].stash_marker_id ? null : files[0].stash_image_id,
          value: { ...trim, crop },
          disabled: locked,
          gifTargetMb: detail.gif_target_mb,
          sourceFps: files[0].fps ?? null,
          gifPreview: !dirty && trim.format !== "video" && files[0].output_mime === `image/${trim.format}` && files[0].prepared ? { url: `${files[0].prepared}?v=${encodeURIComponent(item.updated_at)}`, note: files[0].output_note } : null,
          makingGif,
          onPreviewGif: previewGif,
          onChange: (v) => {
            edit(setTrim)({ inS: v.inS, outS: v.outS, mute: v.mute, flip: v.flip, format: v.format, codec: v.codec, maxEdge: v.maxEdge, loop: v.loop, gifWidth: v.gifWidth, gifFps: v.gifFps, coverT: v.coverT });
            setCrop(v.crop);
          },
          onSaveStill: saveStill
        }
      ) : single ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(CropPreview, { file: files[0], crop }), /* @__PURE__ */ react_default.createElement(CropControls, { crop, disabled: locked, itemId: item.id, onChange: edit(setCrop) })) : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("p", { className: "text-muted mb-1" }, "Files in this post, in order:"), /* @__PURE__ */ react_default.createElement(FileStrip, { files, disabled: locked, onArrange: arrange }), locked ? null : /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "p-0 mb-2 imaglr-touch", onClick: () => arrange([]) }, "Split into separate posts")), /* @__PURE__ */ react_default.createElement(
        TagField,
        {
          tags,
          suggestions: detail.suggestions,
          lowercase: detail.lowercase_tags,
          disabled: locked,
          auto: tagsAuto,
          onChange: (next) => {
            edit(setTags)(next);
            setTagsAuto(false);
            setResetTags(false);
          },
          onReset: () => {
            edit(setTags)(detail.suggestions.active.map((t) => t.tag));
            setTagsAuto(true);
            setResetTags(true);
          }
        }
      ), /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-3" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, fromImaglr ? "Your caption for the reblog" : "Caption", " ", /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, "(optional)")), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          className: "text-input",
          as: "textarea",
          rows: 3,
          value: caption,
          disabled: locked,
          onChange: (e) => edit(setCaption)(e.target.value)
        }
      )), blogs.length > 1 ? /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Blog"), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          className: "text-input",
          as: "select",
          value: blogId ?? "",
          disabled: locked,
          onChange: (e) => edit(setBlogId)(e.target.value ? Number(e.target.value) : null)
        },
        /* @__PURE__ */ react_default.createElement("option", { value: "" }, "Choose a blog\u2026"),
        blogs.map((b) => /* @__PURE__ */ react_default.createElement("option", { key: b.id, value: b.id }, b.label))
      )) : null, fromImaglr ? null : /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Send as", " ", blog ? /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, "(default for ", blog.label, ": ", ACTION_LABELS[blog.default_action].toLowerCase(), ")") : null), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, Object.keys(ACTION_LABELS).map((a) => /* @__PURE__ */ react_default.createElement(
        Button,
        {
          key: a,
          variant: sendAction === a ? "primary" : "secondary",
          disabled: locked,
          onClick: () => {
            edit(setAction)(a);
            setConfirmPublish(false);
          }
        },
        ACTION_LABELS[a]
      ))))), blogs.length === 0 ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "info" }, "Add your imaglr blog first: use the Settings button on the page.") : null, problem ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "warning" }, problem) : null), /* @__PURE__ */ react_default.createElement(Modal.Footer, { className: "imaglr-editor-footer" }, BUSY.includes(item.status) ? /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: cancelSend }, "Stop sending") : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "text-danger mr-auto", onClick: () => setConfirmRemove(true), disabled: locked }, removeLabel), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: cancel, disabled: busy }, "Cancel"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: saveAndClose, disabled: locked || !dirty || busy }, "Save"), fromImaglr ? /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: () => setConfirmReblog(true), disabled: locked || !blog || busy }, "Reblog", blog ? ` to ${blog.label}` : "") : /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: send, disabled: locked || !blog || !!problem || busy }, busy ? "Starting\u2026" : sendButtonLabel(sendAction, blog)))), confirmPublish ? /* @__PURE__ */ react_default.createElement(
        ConfirmDialog,
        {
          title: `Publish now on ${blog?.label}`,
          accept: "Publish now",
          variant: "danger",
          busy,
          onAccept: send,
          onCancel: () => setConfirmPublish(false)
        },
        "This posts publicly on ",
        blog?.label,
        " right away, not as a draft."
      ) : null, confirmReblog && blog ? /* @__PURE__ */ react_default.createElement(
        ConfirmDialog,
        {
          title: `Reblog to ${blog.label}`,
          accept: "Reblog",
          busy,
          onAccept: reblog,
          onCancel: () => setConfirmReblog(false)
        },
        "The original post appears on ",
        blog.label,
        " straight away, with your caption and tags, and this comes off the page."
      ) : null, confirmRemove ? /* @__PURE__ */ react_default.createElement(
        ConfirmDialog,
        {
          title: removeLabel,
          accept: item.kind === "still" ? "Delete" : "Remove tag",
          variant: "danger",
          busy,
          onAccept: remove,
          onCancel: () => setConfirmRemove(false)
        },
        removeQuestion
      ) : null)
    );
  }

  // src/ui/lib/sort.ts
  var ZOOM_WIDTHS = [280, 340, 480, 640];
  var DEFAULTS = {
    sort: "added",
    dir: "desc",
    search: "",
    status: "all",
    types: [],
    orientation: "any",
    view: "grid",
    zoom: 1,
    perPage: 40,
    blog: null,
    sentAs: "all"
  };
  function defaultsFor(tab) {
    return tab === "sent" ? { ...DEFAULTS, sort: "sent" } : { ...DEFAULTS };
  }
  var PAGE_SIZES = [20, 40, 60, 120, 250, 500, 1e3];
  function paginate(list, page, perPage) {
    const size = Math.max(1, perPage);
    const pages = Math.max(1, Math.ceil(list.length / size));
    const current = Math.min(Math.max(1, page), pages);
    return { items: list.slice((current - 1) * size, current * size), page: current, pages };
  }
  var SORTS = {
    sent: [{ key: "sent", label: "Sent" }, { key: "name", label: "Name" }, { key: "blog", label: "Blog" }],
    clips: [
      { key: "added", label: "Added" },
      { key: "name", label: "Name" },
      { key: "length", label: "Length" },
      { key: "size", label: "File size" },
      { key: "created", label: "Created in Stash" },
      { key: "date", label: "Scene date" },
      { key: "dims", label: "Resolution" }
    ],
    images: [
      { key: "added", label: "Added" },
      { key: "name", label: "Name" },
      { key: "type", label: "File type" },
      { key: "size", label: "File size" },
      { key: "created", label: "Created in Stash" },
      { key: "date", label: "Image date" },
      { key: "dims", label: "Resolution" }
    ]
  };
  function num(v) {
    return typeof v === "number" && isFinite(v) ? v : -1;
  }
  function str(v) {
    return typeof v === "string" ? v.toLowerCase() : "";
  }
  function ts(v) {
    const t = typeof v === "string" ? Date.parse(v) : NaN;
    return isNaN(t) ? -1 : t;
  }
  function pixels(c) {
    return num(c.width) > 0 && num(c.height) > 0 ? num(c.width) * num(c.height) : -1;
  }
  function keyOf(c, key) {
    switch (key) {
      case "added":
        return ts(c.first_seen) >= 0 ? ts(c.first_seen) : ts(c.created_at);
      case "name":
        return str(c.title);
      case "size":
        return num(c.bytes);
      case "length":
        return num(c.duration);
      case "type":
        return str(c.format);
      case "created":
        return ts(c.created_at);
      case "date":
        return ts(c.date);
      case "dims":
        return pixels(c);
      case "sent":
      // Sent-tab sorts are applied on the backend; treated like "added" if ever used here
      case "blog":
        return ts(c.created_at);
    }
  }
  function orientationOf(c) {
    const w = num(c.width), h = num(c.height);
    if (w <= 0 || h <= 0) return "any";
    if (Math.abs(w - h) / Math.max(w, h) < 0.02) return "square";
    return w > h ? "landscape" : "portrait";
  }
  function applyControls(list, s) {
    const q = s.search.trim().toLowerCase();
    const out = list.filter((c) => {
      if (q && !`${c.title} ${c.scene_title ?? ""}`.toLowerCase().includes(q)) return false;
      if (s.status !== "all") {
        const st = c.status ?? c.item?.status ?? null;
        if (s.status === "untouched" ? st !== null : st !== s.status) return false;
      }
      if (s.types.length && !s.types.includes((c.format ?? "").toUpperCase())) return false;
      if (s.orientation !== "any" && orientationOf(c) !== s.orientation) return false;
      return true;
    });
    const mult = s.dir === "asc" ? 1 : -1;
    return out.sort((a, b) => {
      const ka = keyOf(a, s.sort), kb = keyOf(b, s.sort);
      let r = typeof ka === "string" && typeof kb === "string" ? ka.localeCompare(kb) : ka - kb;
      if (r === 0) r = ts(b.first_seen) - ts(a.first_seen);
      return r * mult;
    });
  }
  function formatsIn(list) {
    const counts = /* @__PURE__ */ new Map();
    for (const c of list) {
      const f = (c.format ?? "").toUpperCase();
      if (f) counts.set(f, (counts.get(f) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([f]) => f);
  }
  var storageKey = (tab) => `imaglr.controls.${tab}`;
  function loadControls(tab, storage) {
    const base = defaultsFor(tab);
    try {
      const raw = (storage ?? localStorage).getItem(storageKey(tab));
      if (raw) {
        const saved = { ...base, ...JSON.parse(raw) };
        const sorts = (SORTS[tab] ?? SORTS.images).map((s) => s.key);
        return {
          ...base,
          sort: sorts.includes(saved.sort) ? saved.sort : base.sort,
          dir: saved.dir === "asc" ? "asc" : "desc",
          search: typeof saved.search === "string" ? saved.search : "",
          status: typeof saved.status === "string" ? saved.status : "all",
          types: Array.isArray(saved.types) ? saved.types.filter((t) => typeof t === "string") : [],
          orientation: ["portrait", "landscape", "square"].includes(saved.orientation) ? saved.orientation : "any",
          view: saved.view === "list" ? "list" : "grid",
          zoom: Math.min(Math.max(Number(saved.zoom) || 0, 0), ZOOM_WIDTHS.length - 1),
          perPage: Math.max(1, Math.floor(Number(saved.perPage))) || DEFAULTS.perPage,
          blog: typeof saved.blog === "number" ? saved.blog : null,
          sentAs: ["draft", "queue", "publish"].includes(saved.sentAs) ? saved.sentAs : "all"
        };
      }
    } catch {
    }
    return base;
  }
  function changesWhatIsListed(a, b) {
    return a.sort !== b.sort || a.dir !== b.dir || a.search !== b.search || a.status !== b.status || a.types.join() !== b.types.join() || a.orientation !== b.orientation || a.perPage !== b.perPage || a.blog !== b.blog || a.sentAs !== b.sentAs;
  }
  function saveControls(tab, s, storage) {
    try {
      (storage ?? localStorage).setItem(storageKey(tab), JSON.stringify(s));
    } catch {
    }
  }
  function filterCount(s, tab = "images") {
    if (tab === "sent") return (s.blog != null ? 1 : 0) + (s.sentAs !== "all" ? 1 : 0);
    return (s.status !== "all" ? 1 : 0) + (s.types.length ? 1 : 0) + (s.orientation !== "any" ? 1 : 0);
  }
  function cardWidth(containerWidth, zoom) {
    const preferred = ZOOM_WIDTHS[zoom] ?? ZOOM_WIDTHS[1];
    if (!containerWidth) return preferred;
    const usable = containerWidth - 30;
    return usable / Math.ceil(usable / preferred) - 10;
  }

  // src/ui/queue/CardGrid.tsx
  function useContainerWidth() {
    const [width, setWidth] = react_default.useState(0);
    const observer = react_default.useRef(null);
    const attach = react_default.useCallback((el) => {
      observer.current?.disconnect();
      observer.current = null;
      if (!el) return;
      setWidth(el.clientWidth);
      observer.current = new ResizeObserver(() => setWidth(el.clientWidth));
      observer.current.observe(el);
    }, []);
    react_default.useEffect(() => () => observer.current?.disconnect(), []);
    return [width, attach];
  }
  function ThumbImg({ src, fallback, className }) {
    const [current, setCurrent] = react_default.useState(src);
    react_default.useEffect(() => setCurrent(src), [src, fallback]);
    if (!current) return null;
    return /* @__PURE__ */ react_default.createElement(
      "img",
      {
        className,
        src: baseUrl() + current,
        alt: "",
        loading: "lazy",
        onError: () => setCurrent(fallback && current !== fallback ? fallback : null)
      }
    );
  }
  function CardImage({ item }) {
    const [hover, setHover] = react_default.useState(false);
    const canHover = window.matchMedia?.("(hover: hover)").matches;
    return /* @__PURE__ */ react_default.createElement(
      "div",
      {
        className: `image-card-preview${item.portrait ? " portrait" : ""}`,
        onMouseEnter: () => canHover && item.preview && setHover(true),
        onMouseLeave: () => setHover(false)
      },
      hover && item.preview ? /* @__PURE__ */ react_default.createElement("video", { className: "image-card-preview-image", src: baseUrl() + item.preview, autoPlay: true, muted: true, loop: true, playsInline: true }) : /* @__PURE__ */ react_default.createElement(ThumbImg, { className: "image-card-preview-image", src: item.thumb, fallback: item.thumbFallback })
    );
  }
  function Overlays({ item }) {
    const { Badge } = PluginApi.libraries.Bootstrap;
    return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, item.count ? /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-card-count", title: `${item.count} files in one post` }, item.count) : null, item.badge ? /* @__PURE__ */ react_default.createElement(Badge, { variant: item.badge.variant, className: "imaglr-card-status" }, item.badge.text) : null);
  }
  function CardGrid({ items, view, zoom, highlightId, selected, onToggle }) {
    const { Table, Badge } = PluginApi.libraries.Bootstrap;
    const { Link } = PluginApi.libraries.ReactRouterDOM;
    const loaders = [PluginApi.loadableComponents.SceneCard, PluginApi.loadableComponents.Images].filter(Boolean);
    const loading = PluginApi.hooks.useLoadComponents(loaders);
    const GridCard = PluginApi.components.GridCard ?? (loading ? null : void 0);
    const [width, box] = useContainerWidth();
    const isMobile = window.matchMedia("(max-width: 576px)").matches;
    const selecting = !!selected?.size;
    if (view === "list") {
      return /* @__PURE__ */ react_default.createElement(Table, { striped: true, bordered: true, size: "sm", className: "imaglr-table" }, /* @__PURE__ */ react_default.createElement("tbody", null, items.map((c) => /* @__PURE__ */ react_default.createElement("tr", { key: c.id }, onToggle ? (
        // the whole cell toggles: a 22 px checkbox is a poor thumb target
        /* @__PURE__ */ react_default.createElement("td", { className: "select-col", onClick: () => onToggle(c.id, !(selected?.has(c.id) ?? false)) }, /* @__PURE__ */ react_default.createElement(
          "input",
          {
            type: "checkbox",
            className: "mousetrap",
            checked: selected?.has(c.id) ?? false,
            "aria-label": `Select ${c.title}`,
            onChange: (e) => onToggle(c.id, e.target.checked),
            onClick: (e) => e.stopPropagation()
          }
        ))
      ) : null, /* @__PURE__ */ react_default.createElement("td", { className: "imaglr-table-thumb" }, /* @__PURE__ */ react_default.createElement(CardImage, { item: c })), /* @__PURE__ */ react_default.createElement("td", null, /* @__PURE__ */ react_default.createElement(Link, { to: c.url }, c.title), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted" }, c.detail)), /* @__PURE__ */ react_default.createElement("td", { className: "imaglr-table-status" }, c.badge ? /* @__PURE__ */ react_default.createElement(Badge, { variant: c.badge.variant }, c.badge.text) : null)))));
    }
    const w = isMobile ? void 0 : cardWidth(width, zoom);
    return /* @__PURE__ */ react_default.createElement("div", { ref: box, className: "row justify-content-center imaglr-cards" }, items.map(
      (c) => GridCard ? /* @__PURE__ */ react_default.createElement(
        GridCard,
        {
          key: c.id,
          className: `image-card zoom-${zoom} imaglr-grid-card${c.id === highlightId ? " imaglr-card-highlight" : ""}`,
          linkClassName: "image-card-link",
          width: w,
          url: c.url,
          title: c.title,
          image: /* @__PURE__ */ react_default.createElement(CardImage, { item: c }),
          overlays: /* @__PURE__ */ react_default.createElement(Overlays, { item: c }),
          details: /* @__PURE__ */ react_default.createElement("div", { className: "image-card__details" }, /* @__PURE__ */ react_default.createElement("span", null, c.detail)),
          selecting,
          selected: selected?.has(c.id) ?? false,
          onSelectedChanged: onToggle ? (on) => onToggle(c.id, on) : void 0
        }
      ) : /* @__PURE__ */ react_default.createElement("div", { key: c.id, className: "card grid-card image-card imaglr-grid-card", style: w ? { width: w } : void 0 }, /* @__PURE__ */ react_default.createElement("div", { className: "thumbnail-section" }, /* @__PURE__ */ react_default.createElement(Link, { to: c.url, className: "image-card-link" }, /* @__PURE__ */ react_default.createElement(CardImage, { item: c })), /* @__PURE__ */ react_default.createElement(Overlays, { item: c })), /* @__PURE__ */ react_default.createElement("div", { className: "card-section" }, /* @__PURE__ */ react_default.createElement(Link, { to: c.url }, /* @__PURE__ */ react_default.createElement("h5", { className: "card-section-title" }, c.title)), /* @__PURE__ */ react_default.createElement("div", { className: "image-card__details" }, /* @__PURE__ */ react_default.createElement("span", null, c.detail))))
    ));
  }

  // src/ui/queue/Paging.tsx
  function PageSizeSelect({ value, onChange }) {
    const { Form } = PluginApi.libraries.Bootstrap;
    const [custom, setCustom] = react_default.useState(null);
    const options = PAGE_SIZES.includes(value) ? PAGE_SIZES : [...PAGE_SIZES, value].sort((a, b) => a - b);
    const typed = Math.floor(Number(custom));
    return /* @__PURE__ */ react_default.createElement("div", { className: "page-count-container" }, /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        as: "select",
        className: "btn-secondary",
        value: String(value),
        "aria-label": "Items per page",
        onChange: (e) => {
          if (e.target.value === "custom") setCustom(String(value));
          else onChange(Number(e.target.value));
        }
      },
      options.map((n) => /* @__PURE__ */ react_default.createElement("option", { key: n, value: n }, n)),
      /* @__PURE__ */ react_default.createElement("option", { value: "custom" }, "Custom\u2026")
    ), custom !== null ? /* @__PURE__ */ react_default.createElement(
      ConfirmDialog,
      {
        title: "Items per page",
        accept: "Apply",
        disabled: !(typed > 0),
        onAccept: () => {
          onChange(typed);
          setCustom(null);
        },
        onCancel: () => setCustom(null)
      },
      /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          type: "number",
          min: 1,
          className: "text-input",
          value: custom,
          autoFocus: true,
          "aria-label": "Items per page",
          onChange: (e) => setCustom(e.target.value),
          onKeyDown: (e) => {
            if (e.key === "Enter" && typed > 0) {
              onChange(typed);
              setCustom(null);
            }
          }
        }
      )
    ) : null);
  }
  function Pager({ page, perPage, total, onChange }) {
    const { Pagination, PaginationIndex } = PluginApi.components;
    const { Button, ButtonGroup } = PluginApi.libraries.Bootstrap;
    const pages = Math.max(1, Math.ceil(total / perPage));
    if (total === 0) return null;
    if (Pagination && PaginationIndex) {
      return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(PaginationIndex, { itemsPerPage: perPage, currentPage: page, totalItems: total }), /* @__PURE__ */ react_default.createElement(Pagination, { itemsPerPage: perPage, currentPage: page, totalItems: total, onChangePage: onChange }));
    }
    const first = (page - 1) * perPage + 1;
    return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("div", { className: "text-center text-muted" }, first, "-", Math.min(page * perPage, total), " of ", total), pages > 1 ? /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "pagination" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled: page <= 1, onClick: () => onChange(page - 1) }, "\u2039"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled: true }, page, " / ", pages), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled: page >= pages, onClick: () => onChange(page + 1) }, "\u203A")) : null);
  }

  // src/ui/lib/sendAll.ts
  function gifCounts(plan) {
    const live = plan.filter((e) => !e.skip);
    return { gifs: live.filter((e) => e.gif).length, long: live.filter((e) => e.long_gif).length };
  }
  var ACTION_WORDS = { draft: "as drafts", queue: "to the queue" };
  function summarisePlan(plan, fallback) {
    const sending = /* @__PURE__ */ new Map();
    const skipped = /* @__PURE__ */ new Map();
    let downgraded = 0;
    let total = 0;
    for (const e of plan) {
      let blog = e.blog;
      let action = e.action;
      let down = !!e.downgraded;
      if (e.skip === "no_blog" && fallback) {
        blog = fallback.label;
        down = fallback.default_action === "publish";
        action = fallback.default_action === "queue" ? "queue" : "draft";
      } else if (e.skip) {
        const reason = e.reason ?? e.skip;
        skipped.set(reason, (skipped.get(reason) ?? 0) + 1);
        continue;
      }
      const key = `${blog} ${ACTION_WORDS[action ?? "draft"]}`;
      sending.set(key, (sending.get(key) ?? 0) + 1);
      if (down) downgraded++;
      total++;
    }
    return { sending: [...sending], skipped: [...skipped], downgraded, total };
  }

  // src/ui/queue/SendAllDialog.tsx
  function SendAllDialog({ itemIds, selected, onClose }) {
    const { Modal, Button, Form, Alert } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [plan, setPlan] = react_default.useState(null);
    const [blogs, setBlogs] = react_default.useState([]);
    const [fallbackBlog, setFallbackBlog] = react_default.useState(null);
    const [longAsVideo, setLongAsVideo] = react_default.useState(true);
    const [gifFallback, setGifFallback] = react_default.useState(true);
    const [busy, setBusy] = react_default.useState(false);
    const preview = react_default.useCallback(() => {
      runOperation("send_all", { item_ids: itemIds, dry_run: true }).then((r) => setPlan(r.plan), (e) => {
        Toast.error(e);
        onClose(false);
      });
    }, [itemIds]);
    react_default.useEffect(() => {
      preview();
      runOperation("blogs_list").then((r) => setBlogs(r.blogs.filter((b) => !b.paused_reason)), () => void 0);
    }, [preview]);
    if (!plan) {
      const { LoadingIndicator } = PluginApi.components;
      return /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: () => void 0, keyboard: false }, /* @__PURE__ */ react_default.createElement(Modal.Header, null, /* @__PURE__ */ react_default.createElement(Modal.Title, null, selected ? "Send selected" : "Send all")), /* @__PURE__ */ react_default.createElement(Modal.Body, null, LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, { message: "Checking\u2026" }) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Checking\u2026")), /* @__PURE__ */ react_default.createElement(Modal.Footer, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => onClose(false) }, "Cancel")));
    }
    const noBlog = plan.filter((e) => e.skip === "no_blog");
    const fallback = blogs.find((b) => b.id === fallbackBlog) ?? null;
    const { sending, skipped, downgraded, total: ready } = summarisePlan(plan, fallback);
    const gifs = gifCounts(plan);
    async function send() {
      setBusy(true);
      try {
        if (fallbackBlog) {
          await Promise.all(noBlog.map((e) => runOperation("item_update", { item_id: e.id, changes: { blog_id: fallbackBlog } })));
        }
        const r = await runOperation("send_all", {
          item_ids: itemIds,
          long_gifs_as_video: longAsVideo,
          gif_fallback: gifFallback
        });
        const started = r.plan.filter((e) => !e.skip).length;
        Toast.success(`Sending ${started} ${started === 1 ? "item" : "items"}. Progress shows on each card.`);
        onClose(true);
      } catch (e) {
        Toast.error(e);
        setBusy(false);
      }
    }
    return /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: () => void 0, keyboard: false }, /* @__PURE__ */ react_default.createElement(Modal.Header, null, /* @__PURE__ */ react_default.createElement(Modal.Title, null, selected ? "Send selected" : "Send all")), /* @__PURE__ */ react_default.createElement(Modal.Body, null, sending.length ? /* @__PURE__ */ react_default.createElement("ul", { className: "imaglr-plan" }, sending.map(([what, n]) => /* @__PURE__ */ react_default.createElement("li", { key: what }, /* @__PURE__ */ react_default.createElement("strong", null, n), " to ", what))) : /* @__PURE__ */ react_default.createElement("p", null, "Nothing can be sent yet."), downgraded ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "info" }, downgraded, " ", downgraded === 1 ? "item is" : "items are", " set to Publish now and will be saved as drafts instead. Send all never publishes straight away; publish from the editor or on imaglr.") : null, gifs.gifs ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-plan-gifs" }, /* @__PURE__ */ react_default.createElement("div", null, gifs.gifs, " ", gifs.gifs === 1 ? "clip will be a GIF or WebP" : "clips will be GIFs or WebPs", ".", gifs.long ? ` ${gifs.long} ${gifs.long === 1 ? "is" : "are"} longer than ${LONG_GIF_SECONDS} seconds. Send ${gifs.long === 1 ? "it" : "them"} as a video instead?` : null), gifs.long ? /* @__PURE__ */ react_default.createElement(
      Form.Check,
      {
        id: "imaglr-long-gifs",
        type: "checkbox",
        checked: longAsVideo,
        label: `Send the ${gifs.long === 1 ? "long clip" : "long clips"} as ${gifs.long === 1 ? "a video" : "videos"}`,
        onChange: (e) => setLongAsVideo(e.target.checked)
      }
    ) : null, /* @__PURE__ */ react_default.createElement(
      Form.Check,
      {
        id: "imaglr-gif-fallback",
        type: "checkbox",
        checked: gifFallback,
        label: "If a GIF or WebP can't be made small enough, send it as a video.",
        onChange: (e) => setGifFallback(e.target.checked)
      }
    )) : null, noBlog.length && blogs.length ? /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, noBlog.length, " ", noBlog.length === 1 ? "item has" : "items have", " no blog chosen. Send ", noBlog.length === 1 ? "it" : "them", " to:"), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        as: "select",
        className: "text-input",
        value: fallbackBlog ?? "",
        onChange: (e) => setFallbackBlog(e.target.value ? Number(e.target.value) : null)
      },
      /* @__PURE__ */ react_default.createElement("option", { value: "" }, "Skip ", noBlog.length === 1 ? "it" : "them"),
      blogs.map((b) => /* @__PURE__ */ react_default.createElement("option", { key: b.id, value: b.id }, b.label, " (uses its default action)"))
    )) : null, skipped.length ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted" }, "Skipped: ", skipped.map(([reason, n]) => `${n} ${reason}`).join(", "), ".") : null), /* @__PURE__ */ react_default.createElement(Modal.Footer, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => onClose(false) }, "Cancel"), /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", disabled: !ready || busy, onClick: send }, busy ? "Starting\u2026" : `Send ${ready}`)));
  }

  // src/ui/queue/Toolbar.tsx
  var STATUS_FILTERS = ["pending", "ready", "exporting", "sending", "failed"];
  var ORIENTATIONS = ["portrait", "landscape", "square"];
  function icon(name) {
    const { Icon } = PluginApi.components;
    return /* @__PURE__ */ react_default.createElement(Icon, { icon: PluginApi.libraries.FontAwesomeSolid[name] });
  }
  function SearchInput({ value, onChange }) {
    const { Button, FormControl } = PluginApi.libraries.Bootstrap;
    const [text, setText] = react_default.useState(value);
    react_default.useEffect(() => setText(value), [value]);
    react_default.useEffect(() => {
      const timer = window.setTimeout(() => text !== value && onChange(text), 300);
      return () => window.clearTimeout(timer);
    }, [text]);
    return /* @__PURE__ */ react_default.createElement("div", { className: "clearable-input-group search-term-input" }, /* @__PURE__ */ react_default.createElement(
      FormControl,
      {
        className: "clearable-text-field",
        value: text,
        placeholder: "Search\u2026",
        "aria-label": "Search",
        onInput: (e) => setText(e.currentTarget.value),
        onKeyDown: (e) => e.key === "Escape" && e.currentTarget.blur()
      }
    ), text ? /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", className: "clearable-text-field-clear", title: "Clear", onClick: () => {
      setText("");
      onChange("");
    } }, icon("faTimes")) : null);
  }
  function SortBySelect({ tab, controls, onChange }) {
    const { Dropdown, ButtonGroup, Button, InputGroup, OverlayTrigger, Tooltip } = PluginApi.libraries.Bootstrap;
    const options = [...SORTS[tab]].sort((a, b) => a.label.localeCompare(b.label));
    const current = options.find((o) => o.key === controls.sort);
    const asc = controls.dir === "asc";
    return /* @__PURE__ */ react_default.createElement(Dropdown, { as: ButtonGroup, className: "sort-by-select" }, /* @__PURE__ */ react_default.createElement(InputGroup.Prepend, null, /* @__PURE__ */ react_default.createElement(Dropdown.Toggle, { variant: "secondary" }, current?.label ?? "")), /* @__PURE__ */ react_default.createElement(Dropdown.Menu, { className: "bg-secondary text-white" }, options.map((o) => /* @__PURE__ */ react_default.createElement(
      Dropdown.Item,
      {
        key: o.key,
        eventKey: o.key,
        className: "bg-secondary text-white",
        onSelect: () => onChange({ ...controls, sort: o.key })
      },
      o.label
    ))), /* @__PURE__ */ react_default.createElement(OverlayTrigger, { overlay: /* @__PURE__ */ react_default.createElement(Tooltip, { id: "imaglr-sort-direction" }, asc ? "Ascending" : "Descending") }, /* @__PURE__ */ react_default.createElement(
      Button,
      {
        variant: "secondary",
        "aria-label": asc ? "Ascending" : "Descending",
        onClick: () => onChange({ ...controls, dir: asc ? "desc" : "asc" })
      },
      icon(asc ? "faCaretUp" : "faCaretDown")
    )));
  }
  function ViewButtons({ controls, onChange }) {
    const { ButtonGroup, Button, OverlayTrigger, Tooltip, Form } = PluginApi.libraries.Bootstrap;
    const modes = [
      { key: "grid", label: "Grid", icon: "faThLarge" },
      { key: "list", label: "List", icon: "faList" }
    ];
    return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(ButtonGroup, null, modes.map((m) => /* @__PURE__ */ react_default.createElement(OverlayTrigger, { key: m.key, overlay: /* @__PURE__ */ react_default.createElement(Tooltip, { id: `imaglr-view-${m.key}` }, m.label) }, /* @__PURE__ */ react_default.createElement(
      Button,
      {
        variant: "secondary",
        active: controls.view === m.key,
        "aria-label": m.label,
        onClick: () => onChange({ ...controls, view: m.key })
      },
      icon(m.icon)
    )))), /* @__PURE__ */ react_default.createElement("div", { className: "zoom-slider-container" }, controls.view === "grid" ? /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        className: "zoom-slider",
        type: "range",
        min: 0,
        max: ZOOM_WIDTHS.length - 1,
        value: controls.zoom,
        "aria-label": "Card size",
        onChange: (e) => onChange({ ...controls, zoom: Number(e.currentTarget.value) })
      }
    ) : null));
  }
  function FilterTags({ controls, onChange, blogs }) {
    const { Badge, Button } = PluginApi.libraries.Bootstrap;
    const tags = [];
    if (controls.blog != null) {
      tags.push({ label: `Blog: ${blogs?.find((b) => b.id === controls.blog)?.name ?? controls.blog}`, clear: { blog: null } });
    }
    if (controls.sentAs !== "all") tags.push({ label: `Sent as: ${SENT_AS_LABELS[controls.sentAs]}`, clear: { sentAs: "all" } });
    if (controls.status !== "all") {
      tags.push({ label: `Status: ${STATUS_LABELS[controls.status] ?? controls.status}`, clear: { status: "all" } });
    }
    if (controls.types.length) tags.push({ label: `Type: ${controls.types.join(", ")}`, clear: { types: [] } });
    if (controls.orientation !== "any") tags.push({ label: `Orientation: ${controls.orientation}`, clear: { orientation: "any" } });
    if (!tags.length) return null;
    return /* @__PURE__ */ react_default.createElement("div", { className: "wrap-tags filter-tags" }, tags.map((t) => /* @__PURE__ */ react_default.createElement(Badge, { key: t.label, className: "tag-item", variant: "secondary" }, t.label, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", "aria-label": `Remove ${t.label}`, onClick: () => onChange({ ...controls, ...t.clear }) }, icon("faTimes")))), tags.length > 1 ? /* @__PURE__ */ react_default.createElement(
      Button,
      {
        variant: "link",
        className: "clear-all-button",
        onClick: () => onChange({ ...controls, status: "all", types: [], orientation: "any", blog: null, sentAs: "all" })
      },
      "Clear all"
    ) : null);
  }
  function FilterDialog({ tab, controls, items, blogs, onChange, onClose }) {
    const { Modal, Button, Form } = PluginApi.libraries.Bootstrap;
    const [draft, setDraft] = react_default.useState(controls);
    const formats = formatsIn(items);
    return (
      // Stash's own filter dialog closes on Escape and outside clicks (nothing is lost: Apply is explicit).
      /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: onClose }, /* @__PURE__ */ react_default.createElement(Modal.Header, null, /* @__PURE__ */ react_default.createElement(Modal.Title, null, "Filter")), /* @__PURE__ */ react_default.createElement(Modal.Body, null, tab === "sent" ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Blog"), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          as: "select",
          className: "text-input",
          value: draft.blog ?? "",
          onChange: (e) => setDraft({ ...draft, blog: e.target.value ? Number(e.target.value) : null })
        },
        /* @__PURE__ */ react_default.createElement("option", { value: "" }, "Any"),
        (blogs ?? []).map((b) => /* @__PURE__ */ react_default.createElement("option", { key: b.id, value: b.id }, b.name))
      )), /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Sent as"), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          as: "select",
          className: "text-input",
          value: draft.sentAs,
          onChange: (e) => setDraft({ ...draft, sentAs: e.target.value })
        },
        /* @__PURE__ */ react_default.createElement("option", { value: "all" }, "Any"),
        ["draft", "queue", "publish"].map((a) => /* @__PURE__ */ react_default.createElement("option", { key: a, value: a }, SENT_AS_LABELS[a]))
      ))) : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Status"), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          as: "select",
          className: "text-input",
          value: draft.status,
          onChange: (e) => setDraft({ ...draft, status: e.target.value })
        },
        /* @__PURE__ */ react_default.createElement("option", { value: "all" }, "Any"),
        STATUS_FILTERS.map((s) => /* @__PURE__ */ react_default.createElement("option", { key: s, value: s }, STATUS_LABELS[s]))
      )), formats.length > 1 ? /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Type"), formats.map((f) => /* @__PURE__ */ react_default.createElement(
        Form.Check,
        {
          key: f,
          id: `imaglr-type-${f}`,
          type: "checkbox",
          label: f,
          checked: draft.types.includes(f),
          onChange: (e) => setDraft({
            ...draft,
            types: e.target.checked ? [...draft.types, f] : draft.types.filter((t) => t !== f)
          })
        }
      ))) : null, /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Orientation"), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          as: "select",
          className: "text-input",
          value: draft.orientation,
          onChange: (e) => setDraft({ ...draft, orientation: e.target.value })
        },
        /* @__PURE__ */ react_default.createElement("option", { value: "any" }, "Any"),
        ORIENTATIONS.map((o) => /* @__PURE__ */ react_default.createElement("option", { key: o, value: o }, o[0].toUpperCase() + o.slice(1)))
      )))), /* @__PURE__ */ react_default.createElement(Modal.Footer, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: onClose }, "Cancel"), /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: () => {
        onChange(draft);
        onClose();
      } }, "Apply")))
    );
  }
  function Toolbar(props) {
    const { ButtonToolbar, ButtonGroup, Button, Badge, Dropdown } = PluginApi.libraries.Bootstrap;
    const { controls, onChange, selected, selectionActions } = props;
    const [showFilter, setShowFilter] = react_default.useState(false);
    const count = filterCount(controls, props.tab);
    const buttons = selected ? selectionActions.filter((a) => a.primary) : [];
    const menu = selected ? selectionActions.filter((a) => !a.primary) : [];
    return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(ButtonToolbar, { className: `filtered-list-toolbar${selected ? " has-selection" : ""}` }, selected ? /* @__PURE__ */ react_default.createElement("div", { className: "selected-items-info" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", className: "minimal", title: "Select none", onClick: props.onSelectNone }, icon("faTimes")), /* @__PURE__ */ react_default.createElement("span", { className: "selected-count" }, selected), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", className: "minimal", title: "Select all", onClick: props.onSelectAll }, icon("faSquareCheck"))) : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(SearchInput, { value: controls.search, onChange: (search) => onChange({ ...controls, search }) }), /* @__PURE__ */ react_default.createElement(ButtonGroup, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", className: "filter-button", title: "Filter", onClick: () => setShowFilter(true) }, icon("faFilter"), count ? /* @__PURE__ */ react_default.createElement(Badge, { pill: true, variant: "info" }, count) : null)), /* @__PURE__ */ react_default.createElement(SortBySelect, { tab: props.tab, controls, onChange }), /* @__PURE__ */ react_default.createElement(PageSizeSelect, { value: controls.perPage, onChange: (perPage) => onChange({ ...controls, perPage }) })), /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "list-operations" }, props.onSendAll ? /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: props.onSendAll }, selected ? "Send selected" : "Send all") : null, buttons.map((a) => /* @__PURE__ */ react_default.createElement(Button, { key: a.text, variant: a.danger ? "danger" : "secondary", disabled: a.disabled, onClick: a.onClick }, a.text)), /* @__PURE__ */ react_default.createElement(Dropdown, { as: ButtonGroup }, /* @__PURE__ */ react_default.createElement(Dropdown.Toggle, { variant: "secondary", id: "imaglr-more", "aria-label": "More" }, icon("faEllipsisH")), /* @__PURE__ */ react_default.createElement(Dropdown.Menu, { className: "bg-secondary text-white" }, props.onSelectAll ? /* @__PURE__ */ react_default.createElement(Dropdown.Item, { className: "bg-secondary text-white", onClick: props.onSelectAll }, "Select all") : null, selected ? /* @__PURE__ */ react_default.createElement(Dropdown.Item, { className: "bg-secondary text-white", onClick: props.onSelectNone }, "Select none") : null, menu.map((a) => /* @__PURE__ */ react_default.createElement(Dropdown.Item, { key: a.text, className: "bg-secondary text-white", disabled: a.disabled, onClick: a.onClick }, a.text)), /* @__PURE__ */ react_default.createElement(Dropdown.Item, { className: "bg-secondary text-white", onClick: props.onRefresh }, "Refresh")))), /* @__PURE__ */ react_default.createElement(ViewButtons, { controls, onChange })), /* @__PURE__ */ react_default.createElement(FilterTags, { controls, onChange, blogs: props.blogs }), showFilter ? /* @__PURE__ */ react_default.createElement(FilterDialog, { tab: props.tab, controls, items: props.items, blogs: props.blogs, onChange, onClose: () => setShowFilter(false) }) : null);
  }

  // src/ui/queue/QueueTab.tsx
  var BUSY2 = ["exporting", "sending"];
  function cardDetail(card) {
    const count = card.members?.length ?? 0;
    if (count) return `${count} files in one post`;
    if (card.kind === "clip") {
      if (card.output_note) return card.output_note;
      const how = card.send_format === "gif" || card.send_format === "webp" ? [
        card.send_format === "webp" ? "WebP" : "GIF",
        card.loop === "boomerang" || card.loop === "crossfade" ? card.loop : null,
        card.gif_width ? `${card.gif_width} px` : null,
        card.gif_fps ? `${card.gif_fps} fps` : null
      ].filter(Boolean).join(" ") : [card.send_codec === "hevc" ? "H.265" : null, card.max_edge ? edgeLabel(card.max_edge) : null].filter(Boolean).join(" ");
      return [card.whole_scene ? "whole scene" : null, `${(card.duration ?? 0).toFixed(1)} s`, fmtDims(card.width, card.height), how || null].filter(Boolean).join(" \xB7 ");
    }
    return [card.format?.toUpperCase(), fmtDims(card.width, card.height), card.animated ? "animated" : null].filter(Boolean).join(" \xB7 ");
  }
  var EMPTY = {
    clips: (tag) => /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("p", null, "No clips waiting."), /* @__PURE__ */ react_default.createElement("p", null, "In Stash, add the tag ", /* @__PURE__ */ react_default.createElement("strong", null, tag), " to a scene marker (on the scene's ", /* @__PURE__ */ react_default.createElement("strong", null, "Markers"), " tab). Its start and end become the clip; you can trim it here.")),
    images: (tag) => /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("p", null, "No images waiting."), /* @__PURE__ */ react_default.createElement("p", null, "In Stash, tag images ", /* @__PURE__ */ react_default.createElement("strong", null, tag), ", or tick images in any image list and choose", " ", /* @__PURE__ */ react_default.createElement("strong", null, "\u22EF \u2192 Add to imaglr"), ". Stills saved from clips appear here too."))
  };
  function QueueTab({ tab, openId, data, error, load: load2 }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const { useHistory } = PluginApi.libraries.ReactRouterDOM;
    const { LoadingIndicator } = PluginApi.components;
    const Toast = PluginApi.hooks.useToast();
    const history = useHistory();
    const [controls, setControls] = react_default.useState(() => loadControls(tab));
    const [selected, setSelected] = react_default.useState(/* @__PURE__ */ new Set());
    const [sendAll, setSendAll] = react_default.useState(null);
    const [confirmRemove, setConfirmRemove] = react_default.useState(false);
    const [page, setPage] = react_default.useState(1);
    function updateControls(next) {
      if (changesWhatIsListed(controls, next)) setPage(1);
      setControls(next);
      saveControls(tab, next);
    }
    const all = data?.items.filter((c) => c.tab === tab) ?? [];
    const matching = applyControls(all, controls);
    const paged = paginate(matching, page, controls.perPage);
    const items = paged.items;
    react_default.useEffect(() => {
      setSelected((s) => new Set([...s].filter((id) => all.some((c) => c.id === id))));
    }, [data]);
    function toggle(id, on) {
      setSelected((s) => {
        const next = new Set(s);
        if (on) next.add(id);
        else next.delete(id);
        return next;
      });
    }
    const picked = all.filter((c) => selected.has(c.id));
    const files = picked.flatMap((c) => c.members?.length ? c.members : [c]);
    const busyPicked = picked.some((c) => BUSY2.includes(c.status) || c.status === "sent");
    async function run(action, done) {
      try {
        await action();
        Toast.success(done);
        setSelected(/* @__PURE__ */ new Set());
        load2();
      } catch (e) {
        Toast.error(e);
      }
    }
    const stills = picked.filter((c) => c.kind === "still" || c.members?.every((m) => m.kind === "still"));
    const others = picked.length - stills.length;
    const queueTagName = data?.tags.queue.name ?? "imaglr";
    const removeTitle = stills.length && !others ? `Delete ${stills.length === 1 ? "still" : "stills"}` : `Remove "${queueTagName}" tag`;
    const removeQuestion = [
      others ? `Remove the "${queueTagName}" tag in Stash from ${others === 1 ? "this item" : `${others} items`}? ${others === 1 ? "It leaves" : "They leave"} this page; nothing in Stash is deleted.` : null,
      stills.length ? `${stills.length === 1 ? "1 still" : `${stills.length} stills`} will be deleted (stills only exist in the plugin).` : null,
      "Nothing on imaglr is changed."
    ].filter(Boolean).join(" ");
    const selectionActions = [
      {
        text: "Make one post",
        primary: true,
        disabled: files.length < 2 || files.length > MAX_POST_FILES || busyPicked,
        onClick: () => run(
          () => runOperation("post_create", { item_ids: files.map((f) => f.id) }),
          `${files.length} files are now one post.`
        )
      },
      {
        text: "Split into separate posts",
        disabled: !picked.some((c) => c.kind === "set") || busyPicked,
        onClick: () => run(
          () => runOperation("post_split", { post_ids: picked.filter((c) => c.kind === "set").map((c) => c.id) }),
          "Split into separate posts."
        )
      },
      {
        text: removeTitle,
        disabled: busyPicked,
        onClick: () => setConfirmRemove(true)
      }
    ];
    const url = (c) => `${ROUTE}?tab=${tab}&open=${c.id}`;
    const selecting = selected.size > 0;
    let body;
    const problem = error ? /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-danger" }, "Couldn't load the list: ", error, " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "p-0 imaglr-touch", onClick: load2 }, "Try again")) : null;
    if (error && !data) {
      body = problem;
    } else if (!data) {
      body = LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, null) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026");
    } else if (all.length === 0) {
      body = /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-empty text-muted" }, EMPTY[tab](data.tags.queue.name));
    } else if (matching.length === 0) {
      body = /* @__PURE__ */ react_default.createElement("p", { className: "text-muted imaglr-empty" }, "Nothing matches these filters.");
    } else {
      const gridItems = items.map((c) => ({
        id: c.id,
        title: c.title,
        url: url(c),
        thumb: c.thumb,
        preview: c.preview,
        portrait: (c.height ?? 0) > (c.width ?? 0),
        detail: cardDetail(c),
        // Saved from imaglr: never uploaded again (imaglr's terms); the editor offers a reblog instead.
        badge: c.saved_from && !["exporting", "sending", "sent"].includes(c.status) ? { text: "From imaglr", variant: "info" } : { text: STATUS_LABELS[c.status], variant: STATUS_VARIANTS[c.status] },
        count: c.members?.length
      }));
      body = /* @__PURE__ */ react_default.createElement(CardGrid, { items: gridItems, view: controls.view, zoom: controls.zoom, highlightId: openId, selected, onToggle: toggle });
    }
    return /* @__PURE__ */ react_default.createElement("div", null, data && problem, /* @__PURE__ */ react_default.createElement(
      Toolbar,
      {
        tab,
        controls,
        items: all,
        selected: selected.size,
        selectionActions,
        onChange: updateControls,
        onSelectAll: () => setSelected(new Set(items.map((c) => c.id))),
        onSelectNone: () => setSelected(/* @__PURE__ */ new Set()),
        onRefresh: load2,
        onSendAll: matching.length ? () => setSendAll(selected.size ? [...selected] : matching.map((c) => c.id)) : void 0
      }
    ), body, matching.length ? /* @__PURE__ */ react_default.createElement(
      Pager,
      {
        page: paged.page,
        perPage: controls.perPage,
        total: matching.length,
        onChange: (p) => {
          setPage(p);
          window.scrollTo({ top: 0 });
        }
      }
    ) : null, sendAll ? /* @__PURE__ */ react_default.createElement(SendAllDialog, { itemIds: sendAll, selected: selected.size > 0, onClose: (sent) => {
      setSendAll(null);
      if (sent) {
        setSelected(/* @__PURE__ */ new Set());
        load2();
      }
    } }) : null, confirmRemove ? /* @__PURE__ */ react_default.createElement(
      ConfirmDialog,
      {
        title: removeTitle,
        accept: stills.length && stills.length === picked.length ? "Delete" : "Remove",
        variant: "danger",
        onAccept: () => {
          setConfirmRemove(false);
          void run(() => runOperation("remove_from_queue", { item_ids: picked.map((c) => c.id) }), "Removed from this page.");
        },
        onCancel: () => setConfirmRemove(false)
      },
      removeQuestion
    ) : null, openId ? /* @__PURE__ */ react_default.createElement(
      Editor,
      {
        itemId: openId,
        onClose: (changed) => {
          history.replace({ search: `?tab=${tab}` });
          if (changed) load2();
        }
      }
    ) : null);
  }

  // src/ui/sent/SentDialog.tsx
  function SentDialog({ itemId, onClose }) {
    const { Modal, Button, Badge, Alert } = PluginApi.libraries.Bootstrap;
    const { Link } = PluginApi.libraries.ReactRouterDOM;
    const { LoadingIndicator } = PluginApi.components;
    const Toast = PluginApi.hooks.useToast();
    const [item, setItem] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    const [busy, setBusy] = react_default.useState(false);
    const changed = react_default.useRef(false);
    const load2 = react_default.useCallback(() => {
      runOperation("sent_detail", { item_id: itemId }).then((r) => setItem(r.item), (e) => setError(e.message));
    }, [itemId]);
    react_default.useEffect(load2, [load2]);
    async function retry() {
      if (!item) return;
      setBusy(true);
      try {
        await runOperation("retry_follow_up", { item_id: item.id });
        Toast.success(item.action === "publish" ? "Published." : "Added to the queue.");
        changed.current = true;
        load2();
      } catch (e) {
        Toast.error(e);
      } finally {
        setBusy(false);
      }
    }
    async function alwaysDrop(stashTag) {
      try {
        await runOperation("tag_rule_set", { stash_tag: stashTag, imaglr_tags: [] });
        Toast.success(`"${stashTag}" won't be suggested again.`);
      } catch (e) {
        Toast.error(e);
      }
    }
    let body;
    if (error) {
      body = /* @__PURE__ */ react_default.createElement(Alert, { variant: "danger" }, error);
    } else if (!item) {
      body = LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, null) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026");
    } else {
      body = /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, item.followup_failed ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "warning" }, item.error_detail, " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "p-0 align-baseline imaglr-touch", disabled: busy, onClick: retry }, item.action === "publish" ? "Retry publishing" : "Retry adding to queue")) : item.error_detail ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "warning" }, item.error_detail) : null, /* @__PURE__ */ react_default.createElement("ol", { className: "imaglr-strip" }, item.files.map((f) => {
        const to = stashLink(f);
        const img = /* @__PURE__ */ react_default.createElement(ThumbImg, { src: f.thumb, fallback: f.thumb_fallback });
        return /* @__PURE__ */ react_default.createElement("li", { key: f.id, className: "imaglr-strip-item", title: f.title }, to ? /* @__PURE__ */ react_default.createElement(Link, { to, title: `${f.title} in Stash` }, img) : img);
      })), /* @__PURE__ */ react_default.createElement("dl", { className: "row imaglr-sent-facts" }, /* @__PURE__ */ react_default.createElement("dt", { className: "col-4 col-sm-3" }, item.kind === "set" ? "Files" : item.kind === "clip" ? "Clip" : item.kind === "still" ? "Still" : "Image"), /* @__PURE__ */ react_default.createElement("dd", { className: "col-8 col-sm-9" }, item.kind === "set" ? `${item.files.length} files in one post` : stashLink(item.files[0] ?? {}) ? /* @__PURE__ */ react_default.createElement(Link, { to: stashLink(item.files[0]), title: "Open in Stash" }, item.title) : item.title), item.output_note ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("dt", { className: "col-4 col-sm-3" }, "File"), /* @__PURE__ */ react_default.createElement("dd", { className: "col-8 col-sm-9" }, item.output_note)) : null, /* @__PURE__ */ react_default.createElement("dt", { className: "col-4 col-sm-3" }, "Sent as"), /* @__PURE__ */ react_default.createElement("dd", { className: "col-8 col-sm-9" }, /* @__PURE__ */ react_default.createElement(Badge, { variant: item.sent_as === "publish" ? "success" : "primary" }, SENT_AS_LABELS[item.sent_as]), " ", item.blog ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, "on ", /* @__PURE__ */ react_default.createElement("strong", null, item.blog)) : null), /* @__PURE__ */ react_default.createElement("dt", { className: "col-4 col-sm-3" }, "When"), /* @__PURE__ */ react_default.createElement("dd", { className: "col-8 col-sm-9" }, fmtDate(item.sent_at)), /* @__PURE__ */ react_default.createElement("dt", { className: "col-4 col-sm-3" }, "On imaglr"), /* @__PURE__ */ react_default.createElement("dd", { className: "col-8 col-sm-9" }, /* @__PURE__ */ react_default.createElement("a", { href: imaglrLink(item.sent_as, item.post_url), target: "_blank", rel: "noreferrer" }, item.sent_as === "draft" ? "Open imaglr drafts" : "Open the post")), /* @__PURE__ */ react_default.createElement("dt", { className: "col-4 col-sm-3" }, "Tags"), /* @__PURE__ */ react_default.createElement("dd", { className: "col-8 col-sm-9" }, item.tags.length ? item.tags.map((t) => /* @__PURE__ */ react_default.createElement(Badge, { key: t, variant: "secondary", className: "tag-item" }, t)) : /* @__PURE__ */ react_default.createElement("span", { className: "text-muted" }, "None")), item.dropped_tags.length ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("dt", { className: "col-4 col-sm-3" }, "Dropped by imaglr"), /* @__PURE__ */ react_default.createElement("dd", { className: "col-8 col-sm-9" }, (item.dropped ?? item.dropped_tags.map((tag) => ({ tag, from: null }))).map(({ tag, from }) => /* @__PURE__ */ react_default.createElement("span", { key: tag, className: "imaglr-dropped" }, /* @__PURE__ */ react_default.createElement(Badge, { variant: "secondary", className: "tag-item" }, tag), from ? /* @__PURE__ */ react_default.createElement(
        Button,
        {
          variant: "link",
          size: "sm",
          className: "p-0 align-baseline imaglr-touch",
          title: `Never suggest the Stash tag "${from}"`,
          onClick: () => alwaysDrop(from)
        },
        "Always drop"
      ) : null)))) : null, item.caption ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("dt", { className: "col-4 col-sm-3" }, "Caption"), /* @__PURE__ */ react_default.createElement("dd", { className: "col-8 col-sm-9 imaglr-caption" }, item.caption)) : null));
    }
    return (
      // Like Stash's own dialogs (ModalComponent): clicking outside or pressing Escape does nothing.
      /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: () => void 0, keyboard: false, size: "lg", dialogClassName: "imaglr-editor", scrollable: true }, /* @__PURE__ */ react_default.createElement(Modal.Header, null, /* @__PURE__ */ react_default.createElement(Modal.Title, null, "Sent to imaglr ", item ? /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, SENT_AS_LABELS[item.sent_as]) : null)), /* @__PURE__ */ react_default.createElement(Modal.Body, null, body), /* @__PURE__ */ react_default.createElement(Modal.Footer, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: () => onClose(changed.current) }, "Close")))
    );
  }

  // src/ui/sent/SentTab.tsx
  function cardDetail2(item) {
    const when = fmtDate(item.sent_at);
    return item.blog ? `${item.blog} \xB7 ${when}` : when;
  }
  function SentTab({ openId }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const { useHistory } = PluginApi.libraries.ReactRouterDOM;
    const { LoadingIndicator } = PluginApi.components;
    const history = useHistory();
    const [controls, setControls] = react_default.useState(() => loadControls("sent"));
    const [page, setPage] = react_default.useState(1);
    const [data, setData] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    const load2 = react_default.useCallback(() => {
      return runOperation("sent_list", {
        page,
        per_page: controls.perPage,
        q: controls.search,
        sort: controls.sort,
        dir: controls.dir,
        blog_id: controls.blog,
        sent_as: controls.sentAs === "all" ? null : controls.sentAs
      }).then((r) => {
        setData(r);
        setError(null);
        if (r.page !== page) setPage(r.page);
      }, (e) => setError(e.message));
    }, [page, controls.perPage, controls.search, controls.sort, controls.dir, controls.blog, controls.sentAs]);
    react_default.useEffect(() => {
      void load2();
    }, [load2]);
    function updateControls(next) {
      if (changesWhatIsListed(controls, next)) setPage(1);
      setControls(next);
      saveControls("sent", next);
    }
    const filtered = !!controls.search || controls.blog != null || controls.sentAs !== "all";
    let body;
    if (error) {
      body = /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-danger" }, "Couldn't load the sent posts: ", error, " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "p-0 imaglr-touch", onClick: () => void load2() }, "Try again"));
    } else if (!data) {
      body = LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, null) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026");
    } else if (data.total === 0) {
      body = /* @__PURE__ */ react_default.createElement("p", { className: "text-muted imaglr-empty" }, filtered ? "Nothing matches these filters." : "Nothing sent yet.");
    } else {
      const gridItems = data.items.map((item) => ({
        id: item.id,
        title: item.title,
        url: `${ROUTE}?tab=sent&open=${item.id}`,
        thumb: item.thumb,
        thumbFallback: item.thumb_fallback,
        detail: cardDetail2(item),
        badge: item.followup_failed ? { text: item.action === "publish" ? "Publish failed" : "Queue failed", variant: "danger" } : { text: SENT_AS_LABELS[item.sent_as], variant: item.sent_as === "publish" ? "success" : "primary" },
        count: item.files.length > 1 ? item.files.length : void 0
      }));
      body = /* @__PURE__ */ react_default.createElement(CardGrid, { items: gridItems, view: controls.view, zoom: controls.zoom, highlightId: openId });
    }
    return /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(
      Toolbar,
      {
        tab: "sent",
        controls,
        items: [],
        blogs: data?.blogs,
        selected: 0,
        selectionActions: [],
        onChange: updateControls,
        onRefresh: () => void load2()
      }
    ), body, data && data.total > 0 ? /* @__PURE__ */ react_default.createElement(
      Pager,
      {
        page: data.page,
        perPage: controls.perPage,
        total: data.total,
        onChange: (p) => {
          setPage(p);
          window.scrollTo({ top: 0 });
        }
      }
    ) : null, openId ? /* @__PURE__ */ react_default.createElement(
      SentDialog,
      {
        itemId: openId,
        onClose: (changed) => {
          history.replace({ search: "?tab=sent" });
          if (changed) void load2();
        }
      }
    ) : null);
  }

  // src/ui/settings/TagRules.tsx
  function StashTagPicker({ value, onChange }) {
    const Select = PluginApi.libraries.ReactSelect.default;
    const [input, setInput] = react_default.useState("");
    const [found, setFound] = react_default.useState([]);
    react_default.useEffect(() => {
      if (!input.trim()) {
        setFound([]);
        return;
      }
      const timer = window.setTimeout(() => {
        runOperation("stash_tags_find", { q: input }).then((r) => setFound(r.tags), () => setFound([]));
      }, 200);
      return () => window.clearTimeout(timer);
    }, [input]);
    return /* @__PURE__ */ react_default.createElement(
      Select,
      {
        inputId: "imaglr-rule-stash-tag",
        className: "react-select tag-select",
        classNamePrefix: "react-select",
        isClearable: true,
        value: value ? { value, label: value } : null,
        options: found.map((t) => ({ value: t, label: t })),
        inputValue: input,
        onInputChange: (v, meta) => meta.action === "input-change" && setInput(v),
        onChange: (o) => {
          onChange(o?.value ?? null);
          setInput("");
        },
        filterOption: () => true,
        placeholder: "Choose a Stash tag\u2026",
        noOptionsMessage: () => input.trim() ? "No Stash tag with that name" : null,
        styles: { option: (base) => ({ ...base, color: "#000" }) },
        components: { IndicatorSeparator: () => null }
      }
    );
  }
  function TagRules() {
    const { Button, Badge, Form } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [rules, setRules] = react_default.useState([]);
    const [stashTag, setStashTag] = react_default.useState(null);
    const [targets, setTargets] = react_default.useState([]);
    const [lowercase, setLowercase] = react_default.useState(true);
    react_default.useEffect(() => {
      runOperation("tag_rule_list").then((r) => {
        setRules(r.rules);
        setLowercase(r.lowercase_tags);
      }, () => void 0);
    }, []);
    async function save2(tags) {
      try {
        setRules((await runOperation("tag_rule_set", { stash_tag: stashTag, imaglr_tags: tags })).rules);
        setStashTag(null);
        setTargets([]);
      } catch (e) {
        Toast.error(e);
      }
    }
    const [removing, setRemoving] = react_default.useState(null);
    async function remove(tag) {
      try {
        setRules((await runOperation("tag_rule_delete", { stash_tag: tag })).rules);
      } catch (e) {
        Toast.error(e);
      }
      setRemoving(null);
    }
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-settings-section" }, /* @__PURE__ */ react_default.createElement("h5", null, "Tag rules"), /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted" }, "Whenever a Stash tag is suggested for imaglr, send these imaglr tags instead. Include the original if you still want it. A rule with no imaglr tags means the Stash tag is never suggested."), rules.length ? /* @__PURE__ */ react_default.createElement("ul", { className: "imaglr-rules" }, rules.map((r) => /* @__PURE__ */ react_default.createElement("li", { key: r.stash_tag }, /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement("strong", null, r.stash_tag), " \u2192", " ", r.imaglr_tags.length ? r.imaglr_tags.map((t) => /* @__PURE__ */ react_default.createElement(Badge, { key: t, variant: "secondary", className: "tag-item" }, t)) : /* @__PURE__ */ react_default.createElement("em", null, "never suggested")), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-rule-actions" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "p-0 imaglr-touch", onClick: () => {
      setStashTag(r.stash_tag);
      setTargets(r.imaglr_tags);
    } }, "Edit"), /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "text-danger p-0 imaglr-touch", onClick: () => setRemoving(r.stash_tag) }, "Remove"))))) : null, /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, { htmlFor: "imaglr-rule-stash-tag" }, "Stash tag"), /* @__PURE__ */ react_default.createElement(StashTagPicker, { value: stashTag, onChange: setStashTag })), /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, { htmlFor: "imaglr-rule-targets" }, "Send as (imaglr tags)"), /* @__PURE__ */ react_default.createElement(
      TagInput,
      {
        inputId: "imaglr-rule-targets",
        tags: targets,
        lowercase,
        onChange: setTargets,
        placeholder: "Add imaglr tags\u2026"
      }
    )), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-rule-buttons" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", disabled: !stashTag || !targets.length, onClick: () => save2(targets) }, "Save rule"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", disabled: !stashTag, onClick: () => save2([]) }, "Never suggest")), removing ? /* @__PURE__ */ react_default.createElement(
      ConfirmDialog,
      {
        title: `Remove the rule for "${removing}"`,
        accept: "Remove",
        variant: "danger",
        onAccept: () => remove(removing),
        onCancel: () => setRemoving(null)
      },
      'The Stash tag "',
      removing,
      '" goes back to being suggested as it is.'
    ) : null);
  }

  // src/ui/discover/SaveFolderDialog.tsx
  function folderReady(setup) {
    return !!setup && setup.folder_ok && setup.folder_writable;
  }
  function folderProblem(setup) {
    if (!setup?.folder) return null;
    if (!setup.folder_ok) return `${setup.folder} isn't inside one of your Stash libraries any more.`;
    if (!setup.folder_writable) return `Stash can't write to ${setup.folder}. Its library may be read-only.`;
    return null;
  }
  function SaveFolderDialog({ setup, onDone, onCancel }) {
    const { Form } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const usable = setup.libraries.filter((l) => l.videos && l.images).sort((a, b) => Number(b.writable) - Number(a.writable));
    const suggest = (path) => `${path.replace(/[\\/]+$/, "")}${path.includes("\\") ? "\\" : "/"}imaglr`;
    const firstWritable = usable.find((l) => l.writable);
    const [folder, setFolder] = react_default.useState(folderReady(setup) && setup.folder ? setup.folder : firstWritable ? suggest(firstWritable.path) : setup.folder ?? "");
    const [busy, setBusy] = react_default.useState(false);
    const problem = folderProblem(setup);
    async function accept() {
      setBusy(true);
      try {
        onDone(await runOperation("save_folder_set", { folder }));
      } catch (e) {
        Toast.error(e);
        setBusy(false);
      }
    }
    return /* @__PURE__ */ react_default.createElement(
      ConfirmDialog,
      {
        title: "Where should saved posts go?",
        accept: "Use this folder",
        busy,
        disabled: !folder.trim(),
        onAccept: accept,
        onCancel
      },
      problem ? /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-warning" }, problem) : null,
      /* @__PURE__ */ react_default.createElement("p", null, "Saved posts go into a folder inside one of your Stash libraries, so Stash adds them like any other file. Each creator gets a folder of their own."),
      usable.length > 1 ? /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Library"), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          as: "select",
          className: "text-input",
          defaultValue: firstWritable?.path,
          onChange: (e) => setFolder(suggest(e.target.value))
        },
        usable.map((l) => /* @__PURE__ */ react_default.createElement("option", { key: l.path, value: l.path }, l.path, l.writable ? "" : " (read-only)"))
      )) : null,
      /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mb-0" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Folder"), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          className: "text-input",
          value: folder,
          onChange: (e) => setFolder(e.target.value)
        }
      ), usable.length === 0 ? /* @__PURE__ */ react_default.createElement(Form.Text, { className: "text-warning" }, "None of your Stash libraries takes both pictures and videos.") : !firstWritable ? /* @__PURE__ */ react_default.createElement(Form.Text, { className: "text-warning" }, "Stash can't write to any of your libraries. Saving needs one it can write to.") : null)
    );
  }
  function SaveFolderSection() {
    const { Button } = PluginApi.libraries.Bootstrap;
    const [setup, setSetup] = react_default.useState(null);
    const [changing, setChanging] = react_default.useState(false);
    react_default.useEffect(() => {
      runOperation("save_setup").then(setSetup, () => setSetup(null));
    }, []);
    if (!setup?.enabled) return null;
    const problem = folderProblem(setup);
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-settings-section" }, /* @__PURE__ */ react_default.createElement("h5", null, "Saving from imaglr"), /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted mb-2" }, setup.folder ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, "Saved posts go to ", /* @__PURE__ */ react_default.createElement("code", null, setup.folder), ".") : "You'll choose where saved posts go the first time you save one."), problem ? /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-warning" }, problem) : null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => setChanging(true) }, setup.folder ? "Change folder" : "Choose folder"), changing ? /* @__PURE__ */ react_default.createElement(SaveFolderDialog, { setup, onCancel: () => setChanging(false), onDone: (s) => {
      setSetup(s);
      setChanging(false);
    } }) : null);
  }

  // src/ui/discover/ReviewDialog.tsx
  var WHY = {
    rule: "your import rule",
    match: "same name in Stash",
    suggested: "from your tag rule",
    none: ""
  };
  var KIND_LABELS = { tag: "Tag", performer: "Performer", studio: "Studio" };
  function TargetBadge({ target, onRemove }) {
    const { Icon } = PluginApi.components;
    const fa = PluginApi.libraries.FontAwesomeSolid;
    const icon2 = target.kind === "performer" ? fa.faUser : target.kind === "studio" ? fa.faVideo : fa.faTag;
    return /* @__PURE__ */ react_default.createElement("span", { className: "tag-item badge badge-secondary imaglr-target" }, /* @__PURE__ */ react_default.createElement(Icon, { icon: icon2 }), " ", target.name, target.create ? " (new)" : "", onRemove ? /* @__PURE__ */ react_default.createElement("button", { type: "button", className: "imaglr-target-remove", "aria-label": `Remove ${target.name}`, onClick: onRemove }, "\xD7") : null);
  }
  function TargetPicker({ onPick, inputId }) {
    const Select = PluginApi.libraries.ReactSelect.default;
    const [input, setInput] = react_default.useState("");
    const [found, setFound] = react_default.useState([]);
    const [top, setTop] = react_default.useState(null);
    react_default.useEffect(() => {
      if (!input.trim()) {
        setFound(top ?? []);
        return;
      }
      const timer = window.setTimeout(() => {
        runOperation("stash_names_find", { q: input }).then((r) => setFound(r.results), () => setFound([]));
      }, 200);
      return () => window.clearTimeout(timer);
    }, [input, top]);
    function openMenu() {
      if (top) return;
      runOperation("stash_names_find", { q: "" }).then((r) => setTop(r.results), () => setTop([]));
    }
    const text = input.trim();
    const exact = found.some((t) => t.kind === "tag" && t.name.toLowerCase() === text.toLowerCase());
    const options = [
      ...["tag", "performer", "studio"].map((kind) => ({
        label: text ? `${KIND_LABELS[kind]}s` : "Most used tags",
        options: found.filter((t) => t.kind === kind).map((t) => ({ value: `${t.kind}:${t.id}`, label: t.name, target: t }))
      })).filter((g) => g.options.length),
      ...text && !exact ? [{ label: "New", options: [{ value: `new:${text}`, label: `Create tag "${text}"`, target: { kind: "tag", name: text, create: true } }] }] : []
    ];
    return /* @__PURE__ */ react_default.createElement(
      Select,
      {
        inputId,
        className: "react-select imaglr-target-picker",
        classNamePrefix: "react-select",
        value: null,
        options,
        inputValue: input,
        onInputChange: (v, meta) => meta.action === "input-change" && setInput(v),
        onChange: (o) => {
          if (o) onPick(o.target);
          setInput("");
        },
        onMenuOpen: openMenu,
        filterOption: () => true,
        placeholder: "Add\u2026",
        noOptionsMessage: () => text ? "Nothing in Stash by that name" : top ? "Type a name" : "Loading\u2026",
        styles: { option: (base) => ({ ...base, color: "#000" }), menuPortal: (base) => ({ ...base, zIndex: 1100 }) },
        components: { IndicatorSeparator: () => null, DropdownIndicator: () => null },
        menuPlacement: "auto",
        menuPortalTarget: document.body
      }
    );
  }
  function ReviewDialog({ post, blogId, onDone, onCancel }) {
    const { Modal, Button, Form } = PluginApi.libraries.Bootstrap;
    const { LoadingIndicator } = PluginApi.components;
    const Toast = PluginApi.hooks.useToast();
    const [rows, setRows] = react_default.useState(null);
    const [extra, setExtra] = react_default.useState([]);
    const [busy, setBusy] = react_default.useState(false);
    const [error, setError] = react_default.useState(null);
    react_default.useEffect(() => {
      runOperation("save_review", { post_id: post.id, blog_id: blogId ?? void 0 }).then((r) => {
        if (r.saved.length) {
          Toast.success("That post is already in your library.");
          onDone({ post_id: r.credit_id, status: "done", progress: 1, error: null, refs: r.saved });
          return;
        }
        setRows(r.rows.map((row) => ({ ...row, remember: row.source === "rule" })));
      }, (e) => setError(e.message));
    }, [post.id, blogId]);
    function withoutStudios(targets) {
      return targets.filter((t) => t.kind !== "studio");
    }
    function add(index, target) {
      const studio = target.kind === "studio";
      setRows((rs) => rs.map((r, n) => {
        const targets = studio ? withoutStudios(r.targets) : r.targets;
        if (n !== index || targets.some((t) => t.kind === target.kind && t.id === target.id && t.name === target.name)) return { ...r, targets };
        return { ...r, targets: [...targets, target] };
      }));
      setExtra((e) => {
        const kept = studio ? withoutStudios(e) : e;
        return index === null && !kept.some((t) => t.kind === target.kind && t.id === target.id && t.name === target.name) ? [...kept, target] : kept;
      });
    }
    function removeAt(index, target) {
      setRows((rs) => rs.map((r, n) => n === index ? { ...r, targets: r.targets.filter((_, k) => k !== target) } : r));
    }
    async function save2() {
      if (!rows) return;
      setBusy(true);
      try {
        const r = await runOperation("save_post", {
          post_id: post.id,
          blog_id: blogId ?? void 0,
          mapping: rows.map((row) => ({ tag: row.tag, targets: row.targets, remember: row.remember })),
          extra
        });
        onDone(r.save);
      } catch (e) {
        Toast.error(e);
        setBusy(false);
      }
    }
    const who = post.original?.creator.name || post.creator.name;
    return /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: onCancel, size: "lg", className: "imaglr-review" }, /* @__PURE__ */ react_default.createElement(Modal.Header, { closeButton: true }, /* @__PURE__ */ react_default.createElement(Modal.Title, null, "Save to your library")), /* @__PURE__ */ react_default.createElement(Modal.Body, null, /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted" }, who ? `A post by @${who}. ` : "", "Choose what its imaglr tags become in Stash. Tags with nothing chosen are left out."), error ? /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-warning" }, error) : null, !rows && !error ? LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, { small: true }) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026") : null, rows ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-review-rows" }, rows.length === 0 ? /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "This post has no tags.") : null, rows.map((row, n) => /* @__PURE__ */ react_default.createElement("div", { key: row.tag, className: "imaglr-review-row" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-review-tag" }, /* @__PURE__ */ react_default.createElement("strong", null, "#", row.tag), WHY[row.source] && row.targets.length ? /* @__PURE__ */ react_default.createElement("span", { className: "small text-muted" }, " \xB7 ", WHY[row.source]) : null), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-review-targets" }, row.targets.length ? row.targets.map((t, k) => /* @__PURE__ */ react_default.createElement(TargetBadge, { key: `${t.kind}${t.id ?? t.name}`, target: t, onRemove: () => removeAt(n, k) })) : /* @__PURE__ */ react_default.createElement("span", { className: "small text-muted" }, "Left out")), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-review-edit" }, /* @__PURE__ */ react_default.createElement(TargetPicker, { inputId: `imaglr-review-${n}`, onPick: (t) => add(n, t) }), /* @__PURE__ */ react_default.createElement(
      Form.Check,
      {
        id: `imaglr-remember-${n}`,
        type: "checkbox",
        label: "Remember",
        checked: row.remember,
        onChange: (e) => {
          const remember = e.target.checked;
          setRows((rs) => rs.map((r, k) => k === n ? { ...r, remember } : r));
        }
      }
    )))), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-review-row" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-review-tag" }, /* @__PURE__ */ react_default.createElement("strong", null, "Also add")), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-review-targets" }, extra.map((t, k) => /* @__PURE__ */ react_default.createElement(
      TargetBadge,
      {
        key: `${t.kind}${t.id ?? t.name}`,
        target: t,
        onRemove: () => setExtra((e) => e.filter((_, i) => i !== k))
      }
    ))), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-review-edit" }, /* @__PURE__ */ react_default.createElement(TargetPicker, { inputId: "imaglr-review-extra", onPick: (t) => add(null, t) }))), /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted mb-0" }, "Remembered choices apply to every post you save from now on. Change them in the plugin's Settings, under Import rules.")) : null), /* @__PURE__ */ react_default.createElement(Modal.Footer, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: onCancel, disabled: busy }, "Cancel"), /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: save2, disabled: !rows || busy }, busy ? "Saving\u2026" : "Save")));
  }

  // src/ui/settings/ImportRules.tsx
  function ImportRules() {
    const { Button } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [rules, setRules] = react_default.useState(null);
    const [enabled, setEnabled] = react_default.useState(false);
    const [removing, setRemoving] = react_default.useState(null);
    react_default.useEffect(() => {
      runOperation("import_rule_list").then((r) => {
        setRules(r.rules);
        setEnabled(r.enabled);
      }, () => void 0);
    }, []);
    async function remove(tag) {
      try {
        setRules((await runOperation("import_rule_delete", { imaglr_tag: tag })).rules);
      } catch (e) {
        Toast.error(e);
      }
      setRemoving(null);
    }
    if (!enabled && !rules?.length) return null;
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-settings-section" }, /* @__PURE__ */ react_default.createElement("h5", null, "Import rules"), /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted" }, "When you save a post from imaglr, these imaglr tags become these Stash tags, performers or studio. Tick Remember in the save review to add one."), rules?.length ? /* @__PURE__ */ react_default.createElement("ul", { className: "imaglr-rules" }, rules.map((r) => /* @__PURE__ */ react_default.createElement("li", { key: r.imaglr_tag }, /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement("strong", null, "#", r.imaglr_tag), " \u2192", " ", r.targets.length ? r.targets.map((t) => /* @__PURE__ */ react_default.createElement(TargetBadge, { key: `${t.kind}${t.id}`, target: t })) : /* @__PURE__ */ react_default.createElement("em", null, "always left out")), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-rule-actions" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "text-danger p-0 imaglr-touch", onClick: () => setRemoving(r.imaglr_tag) }, "Remove"))))) : /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted" }, "None yet."), removing ? /* @__PURE__ */ react_default.createElement(
      ConfirmDialog,
      {
        title: `Remove the rule for "#${removing}"`,
        accept: "Remove",
        variant: "danger",
        onAccept: () => remove(removing),
        onCancel: () => setRemoving(null)
      },
      '"#',
      removing,
      '" goes back to matching Stash names and aliases when you save.'
    ) : null);
  }

  // src/ui/settings/Settings.tsx
  function Settings({ onClose }) {
    const { Modal, Button, Form, Alert, Badge } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [blogs, setBlogs] = react_default.useState(null);
    const [key, setKey] = react_default.useState("");
    const [defaultAction, setDefaultAction] = react_default.useState("draft");
    const [adding, setAdding] = react_default.useState(false);
    const [checking, setChecking] = react_default.useState(false);
    const [error, setError] = react_default.useState(null);
    const [changed, setChanged] = react_default.useState(false);
    const refresh = react_default.useCallback(() => {
      setChecking(true);
      runOperation("blogs_check").then((r) => setBlogs(r.blogs), (e) => Toast.error(e)).finally(() => setChecking(false));
    }, []);
    react_default.useEffect(() => {
      runOperation("blogs_list").then((r) => {
        setBlogs(r.blogs);
        if (r.blogs.length) refresh();
      }, (e) => Toast.error(e));
    }, [refresh]);
    async function add(e) {
      e.preventDefault();
      setAdding(true);
      setError(null);
      try {
        await runOperation("blog_add", { api_key: key, default_action: defaultAction });
        setKey("");
        setChanged(true);
        refresh();
      } catch (err) {
        setError(err.message);
      } finally {
        setAdding(false);
      }
    }
    async function setAction(blog, action) {
      try {
        const r = await runOperation("blog_set_action", { blog_id: blog.id, action });
        setBlogs((old) => r.blogs.map((b) => ({ ...b, limits: old?.find((o) => o.id === b.id)?.limits })));
        setChanged(true);
      } catch (err) {
        Toast.error(err);
      }
    }
    const [removing, setRemoving] = react_default.useState(null);
    const [resetting, setResetting] = react_default.useState(false);
    const [resetBusy, setResetBusy] = react_default.useState(false);
    async function resetAll() {
      setResetBusy(true);
      try {
        await runOperation("data_reset", {});
        Toast.success("All plugin data deleted.");
        onClose(true);
      } catch (err) {
        Toast.error(err);
        setResetBusy(false);
        setResetting(false);
      }
    }
    async function remove(blog) {
      try {
        setBlogs((await runOperation("blog_remove", { blog_id: blog.id })).blogs);
        setChanged(true);
      } catch (err) {
        Toast.error(err);
      }
      setRemoving(null);
    }
    return /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: () => void 0, keyboard: false, size: "lg", dialogClassName: "imaglr-editor", scrollable: true }, /* @__PURE__ */ react_default.createElement(Modal.Header, null, /* @__PURE__ */ react_default.createElement(Modal.Title, null, "imaglr settings")), /* @__PURE__ */ react_default.createElement(Modal.Body, null, /* @__PURE__ */ react_default.createElement("h5", null, "Blogs"), blogs === null ? /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026") : null, blogs && blogs.length ? /* @__PURE__ */ react_default.createElement("ul", { className: "imaglr-blog-list" }, blogs.map((blog) => {
      const problem = blogProblem(blog);
      const postsLeft = blog.limits?.posts_per_day?.remaining;
      return /* @__PURE__ */ react_default.createElement("li", { key: blog.id, className: "imaglr-blog" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-blog-name" }, blog.url ? /* @__PURE__ */ react_default.createElement("a", { href: blog.url, target: "_blank", rel: "noreferrer" }, blog.label) : blog.label, " ", problem ? /* @__PURE__ */ react_default.createElement(Badge, { variant: "warning" }, "Needs attention") : blog.ok ? /* @__PURE__ */ react_default.createElement(Badge, { variant: "success" }, "OK") : null), /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, "Key ", blog.key_hint, postsLeft != null ? ` \xB7 ${postsLeft} posts left today` : "", blog.checked_at ? ` \xB7 checked ${fmtDate(blog.checked_at)}` : ""), problem ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-warning" }, problem) : null, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-blog-controls" }, /* @__PURE__ */ react_default.createElement(Form.Label, { className: "mb-0", htmlFor: `imaglr-action-${blog.id}` }, "Send as"), /* @__PURE__ */ react_default.createElement(
        Form.Control,
        {
          id: `imaglr-action-${blog.id}`,
          as: "select",
          size: "sm",
          className: "text-input",
          value: blog.default_action,
          onChange: (e) => setAction(blog, e.target.value)
        },
        Object.keys(ACTION_LABELS).map((a) => /* @__PURE__ */ react_default.createElement("option", { key: a, value: a }, ACTION_LABELS[a]))
      ), /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "text-danger", onClick: () => setRemoving(blog) }, "Remove")));
    })) : null, blogs && blogs.length ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-refresh" }, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", size: "sm", onClick: refresh, disabled: checking }, checking ? "Refreshing\u2026" : "Refresh status"), /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, "Asks imaglr for each blog's name, account status and posts left today. Nothing is changed on imaglr.")) : null, /* @__PURE__ */ react_default.createElement(Form, { onSubmit: add, className: "imaglr-add-blog" }, /* @__PURE__ */ react_default.createElement("h6", null, blogs && blogs.length ? "Add a blog" : "Add your imaglr blog"), /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted" }, "On imaglr, open ", /* @__PURE__ */ react_default.createElement("a", { href: "https://imaglr.com/settings", target: "_blank", rel: "noreferrer" }, "Settings \u2192 API"), " and create a key with the ", /* @__PURE__ */ react_default.createElement("strong", null, "read"), " and ", /* @__PURE__ */ react_default.createElement("strong", null, "manage"), " permissions. Add ", /* @__PURE__ */ react_default.createElement("strong", null, "write"), " too if you want to reblog. Each key belongs to one blog. The key is stored only in this plugin and never shown again."), /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "API key"), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        className: "text-input",
        type: "password",
        autoComplete: "off",
        value: key,
        placeholder: "pbk_\u2026",
        onChange: (e) => setKey(e.target.value)
      }
    )), /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Send as, by default"), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        className: "text-input",
        as: "select",
        value: defaultAction,
        onChange: (e) => setDefaultAction(e.target.value)
      },
      Object.keys(ACTION_LABELS).map((a) => /* @__PURE__ */ react_default.createElement("option", { key: a, value: a }, ACTION_LABELS[a]))
    ), /* @__PURE__ */ react_default.createElement(Form.Text, { muted: true }, "You can still choose differently each time you send.")), error ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "danger" }, error) : null, /* @__PURE__ */ react_default.createElement(Button, { type: "submit", variant: "primary", disabled: adding || !key.trim() }, adding ? "Checking the key\u2026" : "Add blog")), /* @__PURE__ */ react_default.createElement(TagRules, null), /* @__PURE__ */ react_default.createElement(SaveFolderSection, null), /* @__PURE__ */ react_default.createElement(ImportRules, null), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-danger-zone" }, /* @__PURE__ */ react_default.createElement("h5", null, "Delete all plugin data"), /* @__PURE__ */ react_default.createElement("p", { className: "text-muted small mb-2" }, "Removes every blog and its key, the sent history, tag rules and working files. Do this before uninstalling if you don't want the keys left behind: Stash's plugin manager leaves the plugin's data folder in place. Nothing in Stash or on imaglr changes."), /* @__PURE__ */ react_default.createElement(Button, { variant: "danger", onClick: () => setResetting(true) }, "Delete all plugin data\u2026"))), /* @__PURE__ */ react_default.createElement(Modal.Footer, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: () => onClose(changed) }, "Close")), resetting ? /* @__PURE__ */ react_default.createElement(
      ConfirmDialog,
      {
        title: "Delete all plugin data",
        accept: "Delete everything",
        variant: "danger",
        busy: resetBusy,
        onAccept: resetAll,
        onCancel: () => setResetting(false)
      },
      "Every blog and API key, the sent history, tag rules and working files are deleted from this plugin. This can't be undone. Nothing in Stash or on imaglr changes."
    ) : null, removing ? /* @__PURE__ */ react_default.createElement(
      ConfirmDialog,
      {
        title: `Remove ${removing.label}`,
        accept: "Remove",
        variant: "danger",
        onAccept: () => remove(removing),
        onCancel: () => setRemoving(null)
      },
      "Its key is deleted from the plugin. Nothing changes on imaglr."
    ) : null);
  }

  // src/ui/discover/PostCard.tsx
  var AutoplayContext = react_default.createContext(false);
  var previews = /* @__PURE__ */ new Map();
  var waiting = [];
  var running = 0;
  var MAX_FETCHES = 2;
  function previewSrc(url) {
    let p = previews.get(url);
    if (!p) {
      p = new Promise((go) => {
        if (running < MAX_FETCHES) {
          running += 1;
          go();
        } else waiting.push(() => {
          running += 1;
          go();
        });
      }).then(() => runOperation("media_preview", { url })).then((r) => baseUrl() + r.src).finally(() => {
        running -= 1;
        waiting.shift()?.();
      });
      p.catch(() => previews.delete(url));
      previews.set(url, p);
    }
    return p;
  }
  var playing = null;
  var wantsSound = false;
  function useInView(ref) {
    const [state, setState] = react_default.useState({ near: false, visible: 0 });
    react_default.useEffect(() => {
      const el = ref.current;
      if (!el || typeof IntersectionObserver === "undefined") return;
      const near = new IntersectionObserver(
        ([e]) => setState((s) => s.near || !e.isIntersecting ? s : { ...s, near: true }),
        { rootMargin: "100% 0px" }
      );
      const seen = new IntersectionObserver(
        ([e]) => setState((s) => ({ ...s, visible: e.intersectionRatio })),
        { threshold: [0, 0.25, 0.6, 0.9] }
      );
      near.observe(el);
      seen.observe(el);
      return () => {
        near.disconnect();
        seen.disconnect();
      };
    }, [ref]);
    return state;
  }
  function start(v, withSound) {
    if (playing && playing !== v) playing.pause();
    playing = v;
    v.muted = !withSound;
    v.play().catch(() => {
      v.muted = true;
      v.play().catch(() => void 0);
    });
  }
  function VideoMedia({ media }) {
    const { Icon } = PluginApi.components;
    const autoplay = react_default.useContext(AutoplayContext);
    const box = react_default.useRef(null);
    const video = react_default.useRef(null);
    const { near, visible } = useInView(box);
    const [wanted, setWanted] = react_default.useState(false);
    const [src, setSrc] = react_default.useState(null);
    const [problem, setProblem] = react_default.useState(null);
    react_default.useEffect(() => {
      if (!(autoplay ? near : wanted) || src || problem) return;
      let live = true;
      previewSrc(media.url).then((s) => live && setSrc(s), (e) => live && setProblem(e.message));
      return () => {
        live = false;
      };
    }, [autoplay, near, wanted, src, problem, media.url]);
    react_default.useEffect(() => {
      const v = video.current;
      if (!v || !src) return;
      if (autoplay && visible >= 0.6) start(v, wantsSound);
      else if (visible < 0.25 && !v.paused) v.pause();
    }, [autoplay, visible, src]);
    react_default.useEffect(() => {
      if (!autoplay && wanted && src && video.current) start(video.current, true);
    }, [autoplay, wanted, src]);
    const waiting2 = autoplay ? !src && !problem : wanted && !src && !problem;
    return /* @__PURE__ */ react_default.createElement("div", { ref: box, className: "imaglr-post-media", style: { aspectRatio: String(mediaRatio(media)) } }, /* @__PURE__ */ react_default.createElement(
      "video",
      {
        ref: video,
        src: src ?? void 0,
        poster: media.thumb ?? void 0,
        loop: true,
        playsInline: true,
        controls: !!src,
        preload: "metadata",
        onVolumeChange: (e) => {
          wantsSound = !e.currentTarget.muted;
        },
        onPlay: (e) => {
          if (playing && playing !== e.currentTarget) playing.pause();
          playing = e.currentTarget;
        }
      }
    ), !autoplay && !wanted ? /* @__PURE__ */ react_default.createElement("button", { type: "button", className: "imaglr-post-play", "aria-label": "Play", onClick: () => setWanted(true) }, /* @__PURE__ */ react_default.createElement(Icon, { icon: PluginApi.libraries.FontAwesomeSolid.faPlay })) : null, waiting2 ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-post-loading" }, /* @__PURE__ */ react_default.createElement("span", { className: "spinner-border spinner-border-sm" })) : null, problem ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-post-problem small" }, problem) : null);
  }
  function PictureMedia({ media }) {
    const direct = media.url.startsWith("https://");
    const box = react_default.useRef(null);
    const { near } = useInView(box);
    const [src, setSrc] = react_default.useState(direct ? media.url : null);
    react_default.useEffect(() => {
      if (!direct && near && !src) previewSrc(media.url).then(setSrc, () => void 0);
    }, [direct, near, src, media.url]);
    return /* @__PURE__ */ react_default.createElement("div", { ref: box, className: "imaglr-post-media", style: { aspectRatio: String(mediaRatio(media)) } }, src ? /* @__PURE__ */ react_default.createElement("img", { src, alt: "", loading: "lazy", decoding: "async" }) : null);
  }
  function Media({ media }) {
    const strip = react_default.useRef(null);
    const [index, setIndex] = react_default.useState(0);
    if (media.length === 0) return null;
    if (media.length === 1) return media[0].kind === "video" ? /* @__PURE__ */ react_default.createElement(VideoMedia, { media: media[0] }) : /* @__PURE__ */ react_default.createElement(PictureMedia, { media: media[0] });
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-post-carousel" }, /* @__PURE__ */ react_default.createElement(
      "div",
      {
        ref: strip,
        className: "imaglr-post-strip",
        onScroll: (e) => setIndex(Math.round(e.currentTarget.scrollLeft / Math.max(1, e.currentTarget.clientWidth)))
      },
      media.map((m, n) => /* @__PURE__ */ react_default.createElement("div", { key: n, className: "imaglr-post-slide" }, m.kind === "video" ? /* @__PURE__ */ react_default.createElement(VideoMedia, { media: m }) : /* @__PURE__ */ react_default.createElement(PictureMedia, { media: m })))
    ), /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-post-counter badge badge-dark" }, index + 1, " / ", media.length));
  }
  function Avatar({ url, name, large, small }) {
    const [src, setSrc] = react_default.useState(url);
    react_default.useEffect(() => setSrc(url), [url]);
    const className = `imaglr-avatar${large ? " imaglr-avatar-large" : small ? " imaglr-avatar-small" : ""}`;
    if (!src) return /* @__PURE__ */ react_default.createElement("span", { className: `${className} imaglr-avatar-letter`, "aria-hidden": "true" }, (name[0] ?? "?").toUpperCase());
    return /* @__PURE__ */ react_default.createElement("img", { className, src, alt: "", loading: "lazy", onError: () => setSrc(src === url ? avatarFallback(url) : null) });
  }
  function LikeButton({ post, onLike }) {
    const { Icon } = PluginApi.components;
    const fa = PluginApi.libraries.FontAwesomeSolid;
    const [liked, setLiked] = react_default.useState(post.liked);
    const [count, setCount] = react_default.useState(post.notes.likes);
    const [busy, setBusy] = react_default.useState(false);
    async function toggle() {
      if (busy) return;
      const was = { liked, count };
      setBusy(true);
      setLiked(!liked);
      setCount(Math.max(0, count + (liked ? -1 : 1)));
      try {
        const r = await onLike(post);
        if (r.liked !== null) setLiked(r.liked);
        if (r.likes !== null) setCount(r.likes);
      } catch {
        setLiked(was.liked);
        setCount(was.count);
      } finally {
        setBusy(false);
      }
    }
    return /* @__PURE__ */ react_default.createElement(
      "button",
      {
        type: "button",
        className: `btn btn-link imaglr-like${liked ? " imaglr-liked" : ""}`,
        onClick: toggle,
        disabled: busy,
        "aria-pressed": liked,
        title: liked ? "Liked: tap to take it back" : "Like"
      },
      /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faHeart }),
      " ",
      shortCount(count)
    );
  }
  function PostCard({ post, save: save2, onCreator, onTag, onSave, onReblog, onLike }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const { Link } = PluginApi.libraries.ReactRouterDOM;
    const { Icon } = PluginApi.components;
    const fa = PluginApi.libraries.FontAwesomeSolid;
    const [expanded, setExpanded] = react_default.useState(false);
    const state = save2 ?? post.save;
    const refs = state?.status === "done" ? state.refs : post.saved;
    const inLibrary = savedPath(refs);
    const saving = !!state && SAVING.includes(state.status);
    const longCaption = post.summary.length > 160 || post.summary.split("\n").length > 3;
    return /* @__PURE__ */ react_default.createElement("article", { className: "card imaglr-post" }, /* @__PURE__ */ react_default.createElement("header", { className: "imaglr-post-head" }, /* @__PURE__ */ react_default.createElement(Avatar, { url: post.creator.avatar, name: post.creator.name }), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-post-who" }, /* @__PURE__ */ react_default.createElement("button", { type: "button", className: "btn btn-link imaglr-post-name", onClick: () => onCreator(post.creator.name) }, post.creator.name || "someone"), post.original ? /* @__PURE__ */ react_default.createElement("span", { className: "small text-muted" }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faRetweet }), " ", /* @__PURE__ */ react_default.createElement("button", { type: "button", className: "btn btn-link imaglr-post-original", onClick: () => onCreator(post.original.creator.name) }, post.original.creator.name || "the original")) : null), /* @__PURE__ */ react_default.createElement("span", { className: "small text-muted imaglr-post-time" }, relativeTime(post.created_at)), post.url ? /* @__PURE__ */ react_default.createElement("a", { className: "btn btn-link imaglr-post-open", href: post.url, target: "_blank", rel: "noopener noreferrer", title: "Open on imaglr" }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faExternalLinkAlt })) : null), /* @__PURE__ */ react_default.createElement(Media, { media: post.media }), /* @__PURE__ */ react_default.createElement("div", { className: "card-body imaglr-post-body" }, post.summary ? /* @__PURE__ */ react_default.createElement("p", { className: `imaglr-post-caption${expanded || !longCaption ? "" : " imaglr-post-caption-short"}` }, post.summary) : null, longCaption && !expanded ? /* @__PURE__ */ react_default.createElement("button", { type: "button", className: "btn btn-link p-0 small", onClick: () => setExpanded(true) }, "more") : null, post.tags.length ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-post-tags" }, post.tags.map((t) => /* @__PURE__ */ react_default.createElement("button", { key: t, type: "button", className: "tag-item badge badge-secondary", onClick: () => onTag(t) }, "#", t))) : null, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-post-actions" }, /* @__PURE__ */ react_default.createElement("span", { className: "small text-muted imaglr-post-notes" }, /* @__PURE__ */ react_default.createElement(LikeButton, { post, onLike }), /* @__PURE__ */ react_default.createElement("span", { className: "ml-2" }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faRetweet }), " ", shortCount(post.notes.reposts))), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => onReblog(post) }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faRetweet }), " Reblog"), post.media.length === 0 ? null : inLibrary ? /* @__PURE__ */ react_default.createElement(Link, { className: "btn btn-secondary imaglr-post-saved", to: `/${inLibrary}` }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faCheck }), " In your library") : saving ? /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", disabled: true }, /* @__PURE__ */ react_default.createElement("span", { className: "spinner-border spinner-border-sm" }), " ", state.status === "scanning" ? "Adding to Stash\u2026" : `Saving\u2026 ${Math.round(state.progress * 100)}%`) : /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: () => onSave(post) }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faDownload }), " ", state?.status === "failed" ? "Try again" : "Save")), state?.status === "failed" && state.error ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-warning mt-2" }, state.error) : null));
  }

  // src/ui/discover/PostFeed.tsx
  function CreatorHeader({ profile }) {
    const { Icon } = PluginApi.components;
    const fa = PluginApi.libraries.FontAwesomeSolid;
    return /* @__PURE__ */ react_default.createElement("div", { className: "card imaglr-creator" }, /* @__PURE__ */ react_default.createElement("div", { className: "card-body" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-creator-head" }, /* @__PURE__ */ react_default.createElement(Avatar, { url: profile.avatar, name: profile.name, large: true }), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement("h4", { className: "mb-1" }, profile.name), /* @__PURE__ */ react_default.createElement("div", { className: "small text-muted" }, shortCount(profile.counts.posts), " posts \xB7 ", shortCount(profile.counts.followers), " followers")), profile.url ? /* @__PURE__ */ react_default.createElement("a", { className: "btn btn-secondary ml-auto", href: profile.url, target: "_blank", rel: "noopener noreferrer" }, /* @__PURE__ */ react_default.createElement(Icon, { icon: fa.faExternalLinkAlt }), " imaglr") : null), profile.description ? /* @__PURE__ */ react_default.createElement("p", { className: "imaglr-creator-bio mt-2 mb-0" }, profile.description) : null));
  }
  function PostFeed({ source, tag, name, blogId, saves, onCreator, onTag, onSave, onReblog, onLike }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const { LoadingIndicator } = PluginApi.components;
    const [posts, setPosts] = react_default.useState([]);
    const [next, setNext] = react_default.useState(null);
    const [profile, setProfile] = react_default.useState(null);
    const [loading, setLoading] = react_default.useState(false);
    const [error, setError] = react_default.useState(null);
    const [ended, setEnded] = react_default.useState(false);
    const sentinel = react_default.useRef(null);
    const busy = react_default.useRef(false);
    const key = `${source}|${tag ?? ""}|${name ?? ""}|${blogId ?? ""}`;
    const current = react_default.useRef(key);
    const load2 = react_default.useCallback(async (link) => {
      if (busy.current) return;
      busy.current = true;
      setLoading(true);
      const asked = key;
      try {
        const page = await runOperation("browse", { source, tag, name, next: link, blog_id: blogId ?? void 0 });
        if (current.current !== asked) return;
        setPosts((old) => {
          const seen = new Set(old.map((p) => p.id));
          return [...link ? old : [], ...page.posts.filter((p) => !link || !seen.has(p.id))];
        });
        if (!link) setProfile(page.profile);
        setNext(page.next);
        setEnded(!page.next);
        setError(null);
      } catch (e) {
        if (current.current === asked) setError(e.message);
      } finally {
        busy.current = false;
        setLoading(false);
      }
    }, [key]);
    react_default.useEffect(() => {
      current.current = key;
      setPosts([]);
      setNext(null);
      setProfile(null);
      setEnded(false);
      setError(null);
      busy.current = false;
      load2(null);
    }, [key]);
    react_default.useEffect(() => {
      const el = sentinel.current;
      if (!el || !next || error || typeof IntersectionObserver === "undefined") return;
      const watch = new IntersectionObserver(([e]) => e.isIntersecting && load2(next), { rootMargin: "150% 0px" });
      watch.observe(el);
      return () => watch.disconnect();
    }, [next, error, load2]);
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-feed" }, profile ? /* @__PURE__ */ react_default.createElement(CreatorHeader, { profile }) : null, posts.map((p) => /* @__PURE__ */ react_default.createElement(
      PostCard,
      {
        key: p.id,
        post: p,
        save: saves.get(p.credit_id) ?? null,
        onCreator,
        onTag,
        onSave,
        onReblog,
        onLike
      }
    )), /* @__PURE__ */ react_default.createElement("div", { ref: sentinel }), loading ? LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, { small: true }) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026") : null, error ? /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-warning imaglr-feed-end" }, error, " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", size: "sm", onClick: () => load2(posts.length ? next : null) }, "Try again")) : null, ended && !loading && !error ? /* @__PURE__ */ react_default.createElement("p", { className: "text-muted text-center imaglr-feed-end" }, posts.length ? "That's everything for now." : "Nothing here yet.") : null);
  }

  // src/ui/discover/Discover.tsx
  var DISCOVER_TABS = [
    { key: "feed", title: "Feed" },
    { key: "likes", title: "Likes" },
    { key: "explore", title: "Explore" }
  ];
  var POLL_MS = 2e3;
  var BLOG_KEY = "imaglr.browseBlog";
  var RECENT_KEY = "imaglr.recentSearches";
  function storedSearches() {
    try {
      const v = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "[]");
      return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
    } catch {
      return [];
    }
  }
  function storedBlog() {
    try {
      const v = window.localStorage.getItem(BLOG_KEY);
      return v ? Number(v) : null;
    } catch {
      return null;
    }
  }
  function useSaves() {
    const [saves, setSaves] = react_default.useState(/* @__PURE__ */ new Map());
    const busy = [...saves.values()].some((s) => SAVING.includes(s.status));
    react_default.useEffect(() => {
      if (!busy) return;
      const timer = window.setTimeout(() => {
        runOperation("save_status").then((r) => {
          setSaves((old) => {
            const fresh = new Map(old);
            for (const s of r.saves) if (fresh.has(s.post_id)) fresh.set(s.post_id, s);
            return fresh;
          });
        }, () => setSaves((old) => new Map(old)));
      }, POLL_MS);
      return () => window.clearTimeout(timer);
    }, [saves, busy]);
    return { saves, put: (s) => setSaves((old) => new Map(old).set(s.post_id, s)) };
  }
  function Explore({ params, recent, following, onSearch, children }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const { Icon } = PluginApi.components;
    const Select = PluginApi.libraries.ReactSelect.default;
    const current = params.get("creator") ? `@${params.get("creator")}` : params.get("tag") ? `#${params.get("tag")}` : params.get("post") ? `Post ${params.get("post")}` : "";
    const shown = current ? { value: current, label: current, kind: "search" } : null;
    const [text, setText] = react_default.useState("");
    const [open, setOpen] = react_default.useState(false);
    const go = (value) => {
      setText("");
      setOpen(false);
      onSearch(value);
    };
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-feed" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-explore-search" }, /* @__PURE__ */ react_default.createElement(
      Select,
      {
        inputId: "imaglr-explore",
        className: "react-select imaglr-explore-select",
        classNamePrefix: "react-select",
        value: shown,
        inputValue: text,
        options: exploreOptions(text, recent, following),
        menuIsOpen: open,
        onMenuOpen: () => setOpen(true),
        onMenuClose: () => setOpen(false),
        onFocus: () => setOpen(true),
        onInputChange: (v, meta) => {
          if (meta.action === "input-change") {
            setText(v);
            setOpen(true);
          }
        },
        onChange: (o) => o && go(o.value),
        onKeyDown: (e) => {
          if (e.key === "Enter" && !open && text.trim()) {
            e.preventDefault();
            go(text);
          }
        },
        filterOption: () => true,
        placeholder: "#tag, @creator or a post link",
        noOptionsMessage: () => null,
        formatOptionLabel: (o, meta) => meta.context === "value" ? o.label : /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-explore-option" }, o.kind === "follow" ? /* @__PURE__ */ react_default.createElement(Avatar, { url: o.avatar ?? null, name: o.label, small: true }) : /* @__PURE__ */ react_default.createElement(Icon, { icon: o.kind === "recent" ? PluginApi.libraries.FontAwesomeSolid.faHistory : PluginApi.libraries.FontAwesomeSolid.faSearch }), /* @__PURE__ */ react_default.createElement("span", null, o.label)),
        styles: { menuPortal: (base) => ({ ...base, zIndex: 1100 }) },
        components: { IndicatorSeparator: () => null, DropdownIndicator: () => null },
        menuPortalTarget: document.body
      }
    ), /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: () => text.trim() ? go(text) : shown ? onSearch(shown.value) : void 0 }, "Go")), children);
  }
  function SinglePost({ id, ...handlers }) {
    const [post, setPost] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    react_default.useEffect(() => {
      setPost(null);
      setError(null);
      runOperation("post_find", { link: id, blog_id: handlers.blogId ?? void 0 }).then((r) => setPost(r.post), (e) => setError(e.message));
    }, [id, handlers.blogId]);
    if (error) return /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-warning" }, error);
    if (!post) return /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026");
    return /* @__PURE__ */ react_default.createElement(
      PostCard,
      {
        post,
        save: handlers.saves.get(post.credit_id) ?? null,
        onCreator: handlers.onCreator,
        onTag: handlers.onTag,
        onSave: handlers.onSave,
        onReblog: handlers.onReblog,
        onLike: handlers.onLike
      }
    );
  }
  function Discover({ tab, params, blogs, go }) {
    const { Form } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [setup, setSetup] = react_default.useState(null);
    const [pendingSave, setPendingSave] = react_default.useState(null);
    const [reblogging, setReblogging] = react_default.useState(null);
    const [reviewing, setReviewing] = react_default.useState(null);
    const [visited, setVisited] = react_default.useState(/* @__PURE__ */ new Set([tab]));
    const [blogId, setBlogId] = react_default.useState(() => {
      const stored = storedBlog();
      return blogs.some((b) => b.id === stored) ? stored : (blogs.find((b) => b.ok) ?? blogs[0])?.id ?? null;
    });
    const { saves, put } = useSaves();
    const [recent, setRecent] = react_default.useState(storedSearches);
    const [following, setFollowing] = react_default.useState([]);
    react_default.useEffect(() => setVisited((v) => v.has(tab) ? v : new Set(v).add(tab)), [tab]);
    react_default.useEffect(() => {
      runOperation("save_setup").then(setSetup, () => setSetup(null));
    }, []);
    react_default.useEffect(() => {
      if (tab !== "explore" || !blogId) return;
      runOperation("following", { blog_id: blogId }).then((r) => setFollowing(r.people), () => setFollowing([]));
    }, [tab === "explore", blogId]);
    const explore = {
      onCreator: (name) => name && go({ tab: "explore", creator: name }, true),
      onTag: (tag2) => go({ tab: "explore", tag: tag2 }, true)
    };
    async function startSave(post, ready = setup) {
      if (!ready || !folderReady(ready)) {
        setPendingSave(post);
        return;
      }
      if (!ready.quick_save) {
        setReviewing(post);
        return;
      }
      put({ post_id: post.credit_id, status: "queued", progress: 0, error: null, refs: [] });
      try {
        const r = await runOperation("save_post", { post_id: post.id, blog_id: blogId ?? void 0 });
        put(r.save);
      } catch (e) {
        put({ post_id: post.credit_id, status: "failed", progress: 0, error: e.message, refs: [] });
        Toast.error(e);
      }
    }
    async function like(post) {
      try {
        return await runOperation("like", { post_id: post.id, blog_id: blogId ?? void 0 });
      } catch (e) {
        Toast.error(e);
        throw e;
      }
    }
    const handlers = { ...explore, saves, blogId, onSave: (p) => startSave(p), onReblog: setReblogging, onLike: like };
    function search(text) {
      const found = parseSearch(text);
      if (!found) return;
      const next = rememberSearch(recent, searchLabel(found, text));
      setRecent(next);
      try {
        window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      } catch {
      }
      go(found.kind === "creator" ? { tab: "explore", creator: found.value } : found.kind === "tag" ? { tab: "explore", tag: found.value } : { tab: "explore", post: found.value }, true);
    }
    if (blogs.length === 0) {
      return /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-info" }, "Add your imaglr blog in Settings to browse imaglr from here.");
    }
    const creator = params.get("creator");
    const tag = params.get("tag");
    const postId = params.get("post");
    return /* @__PURE__ */ react_default.createElement(AutoplayContext.Provider, { value: !!setup?.autoplay }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-discover" }, blogs.length > 1 ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-discover-as" }, /* @__PURE__ */ react_default.createElement("span", { className: "small text-muted" }, "Browsing as"), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        as: "select",
        size: "sm",
        className: "text-input",
        value: blogId ?? "",
        onChange: (e) => {
          const id = Number(e.target.value);
          setBlogId(id);
          try {
            window.localStorage.setItem(BLOG_KEY, String(id));
          } catch {
          }
        }
      },
      blogs.map((b) => /* @__PURE__ */ react_default.createElement("option", { key: b.id, value: b.id }, b.label))
    )) : null, visited.has("feed") ? /* @__PURE__ */ react_default.createElement("div", { hidden: tab !== "feed" }, /* @__PURE__ */ react_default.createElement(PostFeed, { source: "feed", ...handlers })) : null, visited.has("likes") ? /* @__PURE__ */ react_default.createElement("div", { hidden: tab !== "likes" }, /* @__PURE__ */ react_default.createElement(PostFeed, { source: "likes", ...handlers })) : null, tab === "explore" ? /* @__PURE__ */ react_default.createElement(Explore, { params, recent, following, onSearch: search }, creator ? /* @__PURE__ */ react_default.createElement(PostFeed, { source: "creator", name: creator, ...handlers }) : tag ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("h4", { className: "imaglr-explore-title" }, "#", tag), /* @__PURE__ */ react_default.createElement(PostFeed, { source: "tag", tag, ...handlers })) : postId ? /* @__PURE__ */ react_default.createElement(SinglePost, { id: postId, ...handlers }) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Find posts by tag, see everything a creator has posted, or paste a link to a post to save it.")) : null, pendingSave && setup ? /* @__PURE__ */ react_default.createElement(SaveFolderDialog, { setup, onCancel: () => setPendingSave(null), onDone: (s) => {
      setSetup(s);
      const post = pendingSave;
      setPendingSave(null);
      if (folderReady(s)) startSave(post, s);
    } }) : null, reblogging ? /* @__PURE__ */ react_default.createElement(ReblogDialog, { postId: reblogging.id, creator: reblogging.creator.name, blogs, onClose: () => setReblogging(null) }) : null, reviewing ? /* @__PURE__ */ react_default.createElement(
      ReviewDialog,
      {
        post: reviewing,
        blogId,
        onCancel: () => setReviewing(null),
        onDone: (s) => {
          put(s);
          setReviewing(null);
        }
      }
    ) : null));
  }

  // src/ui/PostPage.tsx
  var TABS = [
    { key: "clips", title: "Clips" },
    { key: "images", title: "Images" },
    { key: "sent", title: "Sent" }
  ];
  function isTab(key) {
    return TABS.some((t) => t.key === key);
  }
  function isDiscoverTab(key) {
    return DISCOVER_TABS.some((t) => t.key === key);
  }
  var POLL_MS2 = 2e3;
  var BUSY3 = ["exporting", "sending"];
  function useQueue(paused) {
    const [data, setData] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    const [tick, setTick] = react_default.useState(0);
    const load2 = react_default.useCallback(() => {
      return runOperation("queue").then((d) => {
        setData(d);
        setError(null);
      }, (e) => setError(e.message)).finally(() => setTick((t) => t + 1));
    }, []);
    react_default.useEffect(() => {
      runOperation("recover").catch(() => void 0).finally(load2);
    }, [load2]);
    const inFlight = data?.items.some((c) => BUSY3.includes(c.status)) ?? false;
    react_default.useEffect(() => {
      if (!inFlight || paused || !data) return;
      const timer = window.setTimeout(() => {
        runOperation("send_status").then((s) => {
          const fresh = new Map(s.items.map((i) => [i.id, i]));
          const finished = data.items.some((c) => BUSY3.includes(c.status) && !fresh.has(c.id));
          if (finished) return load2();
          setData({ ...data, items: data.items.map((c) => fresh.has(c.id) ? { ...c, ...fresh.get(c.id) } : c) });
          setTick((t) => t + 1);
        }, (e) => {
          setError(e.message);
          setTick((t) => t + 1);
        });
      }, POLL_MS2);
      return () => window.clearTimeout(timer);
    }, [tick, inFlight, paused, load2]);
    return { data, error, load: load2 };
  }
  function TabTitle({ title, count }) {
    const { Badge } = PluginApi.libraries.Bootstrap;
    return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, title, count ? /* @__PURE__ */ react_default.createElement(Badge, { className: "left-spacing", pill: true, variant: "secondary" }, count) : null);
  }
  function BackendStatus() {
    const [ping, setPing] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    react_default.useEffect(() => {
      runOperation("ping").then(setPing, (e) => setError(e.message));
    }, []);
    if (error) return /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-danger" }, "The plugin's backend isn't working: ", error);
    if (!ping) return null;
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-footer text-muted small" }, "Imaglr Integration v", ping.plugin_version, " \xB7 Stash ", ping.stash_version);
  }
  function PostPage() {
    const { Nav, Tab, Button, Alert, ButtonGroup } = PluginApi.libraries.Bootstrap;
    const { useHistory, useLocation } = PluginApi.libraries.ReactRouterDOM;
    const { Icon } = PluginApi.components;
    const history = useHistory();
    const params = new URLSearchParams(useLocation().search);
    const openId = params.get("open");
    const requested = params.get("tab");
    const [browsing, setBrowsing] = react_default.useState(false);
    const discoverTab = browsing && isDiscoverTab(requested) ? requested : null;
    const tab = isTab(requested) ? requested : "clips";
    const [lastDiscover, setLastDiscover] = react_default.useState(null);
    react_default.useEffect(() => {
      if (discoverTab) setLastDiscover(discoverTab);
    }, [discoverTab]);
    const [blogs, setBlogs] = react_default.useState(null);
    const [showBlogs, setShowBlogs] = react_default.useState(false);
    const [reloadKey, setReloadKey] = react_default.useState(0);
    const queue = useQueue(!!openId || showBlogs);
    const counts = queue.data && {
      clips: queue.data.items.filter((c) => c.tab === "clips").length,
      images: queue.data.items.filter((c) => c.tab === "images").length,
      sent: queue.data.sent_count
    };
    const loadBlogs = react_default.useCallback(() => {
      runOperation("blogs_list").then((r) => setBlogs(r.blogs), () => setBlogs([]));
    }, []);
    react_default.useEffect(loadBlogs, [loadBlogs]);
    react_default.useEffect(() => {
      runOperation("save_setup").then((s) => setBrowsing(s.enabled), () => setBrowsing(false));
    }, []);
    react_default.useEffect(() => {
      const previous = document.title;
      document.title = browsing ? "imaglr | Stash" : "Post to imaglr | Stash";
      return () => {
        document.title = previous;
      };
    }, [browsing]);
    function setTab(key) {
      history.replace({ search: `?tab=${key}` });
    }
    function go(search, push = false) {
      const location = { search: `?${new URLSearchParams(search).toString()}` };
      if (push) history.push(location);
      else history.replace(location);
    }
    const shareTabs = /* @__PURE__ */ react_default.createElement(Tab.Container, { activeKey: tab, onSelect: (key) => key && setTab(key) }, /* @__PURE__ */ react_default.createElement(Nav, { variant: "tabs", className: "imaglr-tabs" }, TABS.map(({ key, title }) => /* @__PURE__ */ react_default.createElement(Nav.Item, { key }, /* @__PURE__ */ react_default.createElement(Nav.Link, { eventKey: key }, /* @__PURE__ */ react_default.createElement(TabTitle, { title, count: counts?.[key] }))))), /* @__PURE__ */ react_default.createElement(Tab.Content, { className: "imaglr-tab-content", key: reloadKey }, /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "clips" }, tab === "clips" ? /* @__PURE__ */ react_default.createElement(QueueTab, { tab: "clips", openId, ...queue }) : null), /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "images" }, tab === "images" ? /* @__PURE__ */ react_default.createElement(QueueTab, { tab: "images", openId, ...queue }) : null), /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "sent" }, tab === "sent" ? /* @__PURE__ */ react_default.createElement(SentTab, { openId }) : null)));
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-page container-fluid" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-page-header" }, /* @__PURE__ */ react_default.createElement("h2", { className: "imaglr-page-title" }, browsing ? "imaglr" : "Post to imaglr"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => setShowBlogs(true) }, /* @__PURE__ */ react_default.createElement(Icon, { icon: PluginApi.libraries.FontAwesomeSolid.faCog }), " Settings")), blogs && blogs.length === 0 ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "info", className: "imaglr-welcome" }, /* @__PURE__ */ react_default.createElement("strong", null, "Add your imaglr blog to start."), " You'll need an API key from imaglr (paid supporters only).", " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", size: "sm", onClick: () => setShowBlogs(true) }, "Open settings")) : null, browsing ? /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented imaglr-sections" }, /* @__PURE__ */ react_default.createElement(Button, { variant: discoverTab ? "secondary" : "primary", onClick: () => setTab(tab) }, "Share"), /* @__PURE__ */ react_default.createElement(Button, { variant: discoverTab ? "primary" : "secondary", onClick: () => setTab(discoverTab ?? "feed") }, "Discover")) : null, lastDiscover || discoverTab ? /* @__PURE__ */ react_default.createElement("div", { hidden: !discoverTab }, /* @__PURE__ */ react_default.createElement(Tab.Container, { activeKey: discoverTab ?? lastDiscover, onSelect: (key) => key && setTab(key) }, /* @__PURE__ */ react_default.createElement(Nav, { variant: "tabs", className: "imaglr-tabs" }, DISCOVER_TABS.map(({ key, title }) => /* @__PURE__ */ react_default.createElement(Nav.Item, { key }, /* @__PURE__ */ react_default.createElement(Nav.Link, { eventKey: key }, title)))), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-tab-content" }, blogs ? /* @__PURE__ */ react_default.createElement(Discover, { tab: discoverTab ?? lastDiscover, params, blogs, go }) : null))) : null, discoverTab ? null : shareTabs, /* @__PURE__ */ react_default.createElement(BackendStatus, null), showBlogs ? /* @__PURE__ */ react_default.createElement(
      Settings,
      {
        onClose: (changed) => {
          setShowBlogs(false);
          if (changed) {
            loadBlogs();
            queue.load();
            setReloadKey((k) => k + 1);
          }
        }
      }
    ) : null);
  }

  // src/ui/index.tsx
  PluginApi.register.route(ROUTE, PostPage);
  PluginApi.patch.before("MainNavBar.MenuItems", (props) => [
    {
      ...props,
      children: /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, props.children, /* @__PURE__ */ react_default.createElement(NavItem, null))
    }
  ]);
  patchImageLists();
  patchCredit();
})();
