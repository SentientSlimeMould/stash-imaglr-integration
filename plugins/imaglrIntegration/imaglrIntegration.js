/* Imaglr Integration for Stash. SPDX-License-Identifier: AGPL-3.0-only
 * Generated from src/ui by scripts/build.mjs. Do not edit. */
"use strict";
(() => {
  // src/ui/shims/react.ts
  var react_default = PluginApi.React;

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
    const parts = [`${noun(result.added)} added to imaglr.`];
    if (result.already) parts.push(`${noun(result.already)} already there.`);
    return parts.join(" ");
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
        if (asOnePost && result.post_id) history.push(`${ROUTE}?open=${result.post_id}`);
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
            if (result.post_id) history.push(`${ROUTE}?open=${result.post_id}`);
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
          icon: PluginApi.libraries.FontAwesomeSolid.faPaperPlane,
          className: "nav-menu-icon d-block d-xl-inline mb-2 mb-xl-0"
        }
      ),
      /* @__PURE__ */ react_default.createElement("span", null, "imaglr")
    ));
  }

  // src/ui/lib/crop.ts
  var ASPECTS = { original: null, "9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1 };
  function normCrop(srcW, srcH, aspect, position) {
    const a = ASPECTS[aspect];
    if (a == null || srcW <= 0 || srcH <= 0) return { x: 0, y: 0, w: 1, h: 1, axis: "none" };
    const s = srcW / srcH;
    if (Math.abs(s - a) < 1e-6) return { x: 0, y: 0, w: 1, h: 1, axis: "none" };
    let w = 1, h = 1;
    if (a < s) w = a / s;
    else h = s / a;
    const p = Math.min(1, Math.max(0, position));
    return { x: (1 - w) * p, y: (1 - h) * p, w, h, axis: w < 1 ? "x" : h < 1 ? "y" : "none" };
  }
  function displayedRect(cw, ch, srcW, srcH) {
    if (srcW <= 0 || srcH <= 0 || cw <= 0 || ch <= 0) return { dx: 0, dy: 0, dw: cw, dh: ch };
    const scale = Math.min(cw / srcW, ch / srcH);
    const dw = srcW * scale, dh = srcH * scale;
    return { dx: (cw - dw) / 2, dy: (ch - dh) / 2, dw, dh };
  }
  function overlayRect(cw, ch, srcW, srcH, aspect, position) {
    const { dx, dy, dw, dh } = displayedRect(cw, ch, srcW, srcH);
    const n = normCrop(srcW, srcH, aspect, position);
    return { left: dx + n.x * dw, top: dy + n.y * dh, width: n.w * dw, height: n.h * dh, axis: n.axis };
  }

  // src/ui/lib/tags.ts
  var MAX_TAGS = 30;
  var MAX_LEN = 64;
  function normalise(name, lowercase) {
    const s = name.trim().replace(/\s+/g, " ");
    return lowercase ? s.toLowerCase() : s;
  }
  function chipsFromSuggestions(s, selected) {
    const chips = [];
    const seen = /* @__PURE__ */ new Set();
    const sel = selected ? new Set(selected.map((t) => t.toLowerCase())) : null;
    for (const t of s?.active ?? []) {
      seen.add(t.tag.toLowerCase());
      const on = sel ? sel.has(t.tag.toLowerCase()) : true;
      chips.push({ name: t.tag, source: t.source, state: on ? "active" : "parked", reason: on ? void 0 : "removed", original: t.original });
    }
    for (const t of s?.greyed ?? []) {
      if (seen.has(t.tag.toLowerCase())) continue;
      seen.add(t.tag.toLowerCase());
      if (t.reason === "too_long") {
        chips.push({ name: t.tag, source: t.source, state: "too_long", reason: `over ${MAX_LEN} characters`, original: t.original });
      } else {
        const on = sel ? sel.has(t.tag.toLowerCase()) : false;
        chips.push({
          name: t.tag,
          source: t.source,
          state: on ? "active" : "parked",
          reason: on ? void 0 : `over the ${MAX_TAGS}-tag limit`,
          original: t.original
        });
      }
    }
    for (const t of selected ?? []) {
      if (!seen.has(t.toLowerCase())) {
        seen.add(t.toLowerCase());
        chips.push({ name: t, source: "manual", state: "active" });
      }
    }
    return chips;
  }
  function activeNames(chips) {
    return chips.filter((c) => c.state === "active").map((c) => c.name);
  }
  function addTag(chips, raw, lowercase) {
    const name = normalise(raw, lowercase);
    if (!name) return { ok: false, error: "Empty tag" };
    if (name.length > MAX_LEN) return { ok: false, error: `Tag is ${name.length} characters; the limit is ${MAX_LEN}` };
    const dup = chips.find((c) => c.name.toLowerCase() === name.toLowerCase());
    if (dup) {
      if (dup.state === "active") return { ok: false, error: "Already added", existing: dup.name };
      if (dup.state === "too_long") return { ok: false, error: "That tag is too long", existing: dup.name };
      return activate(chips, dup.name);
    }
    const room = activeNames(chips).length < MAX_TAGS;
    const chip = room ? { name, source: "manual", state: "active" } : { name, source: "manual", state: "parked", reason: `over the ${MAX_TAGS}-tag limit` };
    return { ok: true, chips: [...chips, chip], parked: !room };
  }
  function activate(chips, name) {
    if (activeNames(chips).length >= MAX_TAGS) return { ok: false, error: `Remove a tag first (limit ${MAX_TAGS})` };
    return {
      ok: true,
      parked: false,
      chips: chips.map((c) => c.name === name && c.state !== "too_long" ? { ...c, state: "active", reason: void 0 } : c)
    };
  }
  function removeTag(chips, name) {
    return chips.map((c) => c.name === name ? c.source === "manual" ? null : { ...c, state: "parked", reason: "removed" } : c).filter((c) => c !== null);
  }

  // src/ui/lib/send.ts
  var ACTION_LABELS = {
    draft: "Save as draft",
    queue: "Add to queue",
    publish: "Publish now"
  };
  var SENT_AS_LABELS = {
    draft: "Draft",
    queue: "Queued",
    publish: "Published"
  };
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

  // src/ui/editor/TagEditor.tsx
  var SOURCE_LABELS = {
    marker: "marker",
    scene: "scene",
    performer: "performer",
    studio: "studio",
    image: "image",
    gallery: "gallery",
    manual: "added"
  };
  function TagEditor({ chips, lowercase, disabled, onChange }) {
    const { Button, Form, InputGroup } = PluginApi.libraries.Bootstrap;
    const [text, setText] = react_default.useState("");
    const [message, setMessage] = react_default.useState(null);
    const count = activeNames(chips).length;
    function add() {
      const result = addTag(chips, text, lowercase);
      if (!result.ok) {
        setMessage(result.error);
        return;
      }
      onChange(result.chips);
      setText("");
      setMessage(result.parked ? `Parked: already ${MAX_TAGS} tags. Remove one to use it.` : null);
    }
    function reactivate(name) {
      const result = activate(chips, name);
      if (result.ok) onChange(result.chips);
      else setMessage(result.error);
    }
    const active = chips.filter((c) => c.state === "active");
    const parked = chips.filter((c) => c.state !== "active");
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-tags" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-tags-header" }, /* @__PURE__ */ react_default.createElement("strong", null, "Tags"), /* @__PURE__ */ react_default.createElement("span", { className: count > MAX_TAGS ? "text-danger" : "text-muted" }, count, " / ", MAX_TAGS)), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-chips" }, active.length === 0 ? /* @__PURE__ */ react_default.createElement("span", { className: "text-muted" }, "No tags yet.") : null, active.map((chip) => /* @__PURE__ */ react_default.createElement("span", { key: chip.name, className: "imaglr-chip", title: chip.original ? `from Stash: ${chip.original}` : void 0 }, chip.name, /* @__PURE__ */ react_default.createElement("small", { className: "imaglr-chip-source" }, SOURCE_LABELS[chip.source] ?? chip.source), disabled ? null : /* @__PURE__ */ react_default.createElement(
      "button",
      {
        type: "button",
        className: "imaglr-chip-remove",
        "aria-label": `Remove ${chip.name}`,
        onClick: () => onChange(removeTag(chips, chip.name))
      },
      "\xD7"
    )))), disabled ? null : /* @__PURE__ */ react_default.createElement(InputGroup, { className: "imaglr-tag-input" }, /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        className: "text-input",
        value: text,
        placeholder: "Add a tag",
        maxLength: 80,
        onChange: (e) => {
          setText(e.target.value);
          setMessage(null);
        },
        onKeyDown: (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }
      }
    ), /* @__PURE__ */ react_default.createElement(InputGroup.Append, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: add, disabled: !text.trim() }, "Add"))), message ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-warning mt-1" }, message) : null, parked.length ? /* @__PURE__ */ react_default.createElement("details", { className: "imaglr-parked" }, /* @__PURE__ */ react_default.createElement("summary", { className: "text-muted" }, "Not included (", parked.length, ")"), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-chips" }, parked.map((chip) => /* @__PURE__ */ react_default.createElement(
      "button",
      {
        key: chip.name,
        type: "button",
        className: "imaglr-chip imaglr-chip-parked",
        disabled: disabled || chip.state === "too_long",
        onClick: () => reactivate(chip.name),
        title: chip.reason
      },
      chip.state === "too_long" ? chip.name : `+ ${chip.name}`,
      /* @__PURE__ */ react_default.createElement("small", { className: "imaglr-chip-source" }, chip.reason)
    )))) : null);
  }

  // src/ui/editor/Editor.tsx
  var BUSY = ["exporting", "sending"];
  function CropPreview({ file, aspect, position }) {
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
    const rect = overlayRect(size.w, size.h, size.sw, size.sh, aspect, position);
    const src = file.image ?? file.thumb;
    return /* @__PURE__ */ react_default.createElement("div", { ref: box, className: "imaglr-preview" }, src ? /* @__PURE__ */ react_default.createElement("img", { src: baseUrl() + src, alt: "", onLoad: (e) => measure(e.currentTarget) }) : null, rect.axis !== "none" ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-crop", style: { left: rect.left, top: rect.top, width: rect.width, height: rect.height } }) : null);
  }
  function FileStrip({ files, disabled, onArrange }) {
    const ids = files.map((f) => f.id);
    const move = (from, to) => {
      const next = [...ids];
      next.splice(to, 0, next.splice(from, 1)[0]);
      onArrange(next);
    };
    return /* @__PURE__ */ react_default.createElement("ol", { className: "imaglr-strip" }, files.map((f, n) => /* @__PURE__ */ react_default.createElement("li", { key: f.id, className: "imaglr-strip-item" }, f.thumb ? /* @__PURE__ */ react_default.createElement("img", { src: baseUrl() + f.thumb, alt: "" }) : null, /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-strip-number" }, n + 1), disabled ? null : /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-strip-actions" }, /* @__PURE__ */ react_default.createElement("button", { type: "button", "aria-label": "Move earlier", disabled: n === 0, onClick: () => move(n, n - 1) }, "\u25C0"), /* @__PURE__ */ react_default.createElement("button", { type: "button", "aria-label": "Remove from this post", onClick: () => onArrange(ids.filter((i) => i !== f.id)) }, "\xD7"), /* @__PURE__ */ react_default.createElement("button", { type: "button", "aria-label": "Move later", disabled: n === files.length - 1, onClick: () => move(n, n + 1) }, "\u25B6")))));
  }
  function Editor({ itemId, onClose }) {
    const { Modal, Button, Form, ButtonGroup, Alert, ProgressBar } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [detail, setDetail] = react_default.useState(null);
    const [chips, setChips] = react_default.useState([]);
    const [caption, setCaption] = react_default.useState("");
    const [crop, setCrop] = react_default.useState({ aspect: "original", position: 0.5 });
    const [blogId, setBlogId] = react_default.useState(null);
    const [action, setAction] = react_default.useState(null);
    const [confirmPublish, setConfirmPublish] = react_default.useState(false);
    const [busy, setBusy] = react_default.useState(false);
    const [changed, setChanged] = react_default.useState(false);
    const [dirty, setDirty] = react_default.useState(false);
    const load = react_default.useCallback(() => {
      runOperation("item_detail", { item_id: itemId }).then((d) => {
        setDetail(d);
        setChips(chipsFromSuggestions(d.suggestions, d.item.tags));
        setCaption(d.item.caption);
        setCrop(d.item.crop);
        setBlogId(d.item.blog_id);
        setAction(d.item.action);
        setDirty(false);
      }, (e) => {
        Toast.error(e);
        onClose(true);
      });
    }, [itemId]);
    react_default.useEffect(load, [load]);
    if (!detail) return null;
    const { item, files, blogs } = detail;
    const locked = BUSY.includes(item.status) || busy;
    const blog = pickBlog(blogs, blogId);
    const sendAction = effectiveAction(blog, action);
    const problem = blog ? blogProblem(blog) : null;
    const single = files.length === 1 && item.kind !== "set";
    function edit(setter) {
      return (value) => {
        setter(value);
        setDirty(true);
      };
    }
    async function save() {
      if (!dirty) return;
      await runOperation("item_update", {
        item_id: item.id,
        changes: { tags: activeNames(chips), caption, crop, blog_id: blogId, action }
      });
      setDirty(false);
      setChanged(true);
    }
    async function close() {
      try {
        await save();
      } catch (e) {
        Toast.error(e);
      }
      onClose(changed || dirty);
    }
    async function send() {
      if (sendAction === "publish" && !confirmPublish) {
        setConfirmPublish(true);
        return;
      }
      setBusy(true);
      try {
        await save();
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
        await save();
        const result = await runOperation("post_arrange", { item_id: item.id, item_ids: ids });
        setChanged(true);
        if (result.post_id) load();
        else onClose(true);
      } catch (e) {
        Toast.error(e);
      }
    }
    async function cancelSend() {
      await runOperation("cancel", { item_id: item.id }).catch((e) => Toast.error(e));
      onClose(true);
    }
    async function remove() {
      if (!window.confirm("Take this off the imaglr page? Its queue tag is removed in Stash; nothing is deleted.")) return;
      try {
        await runOperation("remove_from_queue", { item_id: item.id });
        onClose(true);
      } catch (e) {
        Toast.error(e);
      }
    }
    return /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: close, size: "lg", dialogClassName: "imaglr-editor", scrollable: true }, /* @__PURE__ */ react_default.createElement(Modal.Header, { closeButton: true }, /* @__PURE__ */ react_default.createElement(Modal.Title, null, item.kind === "set" ? `Post of ${files.length}` : item.source_title, " ", /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, STATUS_LABELS[item.status]))), /* @__PURE__ */ react_default.createElement(Modal.Body, null, item.error_detail && !BUSY.includes(item.status) ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "warning" }, item.error_detail) : null, BUSY.includes(item.status) ? /* @__PURE__ */ react_default.createElement("div", { className: "mb-3" }, /* @__PURE__ */ react_default.createElement(ProgressBar, { now: Math.round(item.progress * 100), label: STATUS_LABELS[item.status] })) : null, single ? /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(CropPreview, { file: files[0], aspect: crop.aspect, position: crop.position }), /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-2" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Crop"), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, Object.keys(ASPECTS).map((a) => /* @__PURE__ */ react_default.createElement(
      Button,
      {
        key: a,
        variant: crop.aspect === a ? "primary" : "secondary",
        disabled: locked,
        onClick: () => edit(setCrop)({ ...crop, aspect: a })
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
        disabled: locked,
        "aria-label": "Crop position",
        className: "mt-2",
        onChange: (e) => edit(setCrop)({ ...crop, position: Number(e.target.value) })
      }
    ) : null)) : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("p", { className: "text-muted mb-1" }, "Files in this post, in order:"), /* @__PURE__ */ react_default.createElement(FileStrip, { files, disabled: locked, onArrange: arrange }), locked ? null : /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "p-0 mb-2", onClick: () => arrange([]) }, "Split into separate posts")), /* @__PURE__ */ react_default.createElement(TagEditor, { chips, lowercase: detail.lowercase_tags, disabled: locked, onChange: edit(setChips) }), /* @__PURE__ */ react_default.createElement(Form.Group, { className: "mt-3" }, /* @__PURE__ */ react_default.createElement(Form.Label, null, "Caption ", /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, "(optional)")), /* @__PURE__ */ react_default.createElement(
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
    )) : null, /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "When sent", " ", blog ? /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, "(default for ", blog.label, ": ", ACTION_LABELS[blog.default_action].toLowerCase(), ")") : null), /* @__PURE__ */ react_default.createElement("div", null, /* @__PURE__ */ react_default.createElement(ButtonGroup, { className: "imaglr-segmented" }, Object.keys(ACTION_LABELS).map((a) => /* @__PURE__ */ react_default.createElement(
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
    ))))), blogs.length === 0 ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "info" }, "Add your imaglr blog first: use the Blogs button on the page.") : null, problem ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "warning" }, problem) : null), /* @__PURE__ */ react_default.createElement(Modal.Footer, { className: "imaglr-editor-footer" }, BUSY.includes(item.status) ? /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: cancelSend }, "Stop sending") : /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "text-danger mr-auto", onClick: remove, disabled: locked }, "Remove from imaglr"), confirmPublish ? /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-confirm" }, "Posts publicly on ", blog?.label, " right away.", /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => setConfirmPublish(false) }, "Cancel"), /* @__PURE__ */ react_default.createElement(Button, { variant: "danger", onClick: send, disabled: busy }, "Publish now")) : /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", onClick: send, disabled: locked || !blog || !!problem }, busy ? "Starting\u2026" : sendButtonLabel(sendAction, blog)))));
  }

  // src/ui/lib/format.ts
  function fmtDims(w, h) {
    return w && h ? `${w}\xD7${h}` : "\u2013";
  }
  function fmtDate(iso) {
    if (!iso) return "\u2013";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString(void 0, { dateStyle: "medium", timeStyle: "short" });
  }

  // src/ui/queue/ItemCard.tsx
  function ItemCard({ card, highlighted }) {
    const { Badge } = PluginApi.libraries.Bootstrap;
    const ref = react_default.useRef(null);
    const count = card.members?.length ?? 0;
    react_default.useEffect(() => {
      if (highlighted) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, [highlighted]);
    const detail = count ? `${count} files in one post` : [card.format?.toUpperCase(), fmtDims(card.width, card.height), card.animated ? "animated" : null].filter(Boolean).join(" \xB7 ");
    return /* @__PURE__ */ react_default.createElement(
      "div",
      {
        ref,
        className: `imaglr-card card${count ? " imaglr-card-stack" : ""}${highlighted ? " imaglr-card-highlight" : ""}`
      },
      /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-card-thumb" }, card.thumb ? /* @__PURE__ */ react_default.createElement("img", { src: baseUrl() + card.thumb, alt: "", loading: "lazy" }) : null, count ? /* @__PURE__ */ react_default.createElement("span", { className: "imaglr-card-count" }, count) : null, /* @__PURE__ */ react_default.createElement(Badge, { variant: STATUS_VARIANTS[card.status], className: "imaglr-card-status" }, STATUS_LABELS[card.status])),
      /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-card-body" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-card-title", title: card.title }, card.title), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-card-detail text-muted" }, detail))
    );
  }

  // src/ui/queue/ImagesTab.tsx
  var POLL_MS = 2e3;
  function ImagesTab({ openId }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const { LoadingIndicator } = PluginApi.components;
    const [data, setData] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    const [loading, setLoading] = react_default.useState(false);
    const [editing, setEditing] = react_default.useState(openId);
    const load = react_default.useCallback(() => {
      setLoading(true);
      return runOperation("images_queue").then((d) => {
        setData(d);
        setError(null);
      }, (e) => setError(e.message)).finally(() => setLoading(false));
    }, []);
    react_default.useEffect(() => {
      runOperation("recover").catch(() => void 0).finally(load);
    }, [load]);
    const inFlight = data?.items.some((c) => c.status === "exporting" || c.status === "sending");
    react_default.useEffect(() => {
      if (!inFlight || editing) return;
      const timer = window.setTimeout(load, POLL_MS);
      return () => window.clearTimeout(timer);
    }, [data, inFlight, editing, load]);
    if (error) {
      return /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-danger" }, "Couldn't load the queue: ", error, " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "p-0", onClick: load }, "Try again"));
    }
    if (!data) return LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, null) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026");
    return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-toolbar" }, /* @__PURE__ */ react_default.createElement("span", { className: "text-muted" }, data.items.length, " ", data.items.length === 1 ? "item" : "items"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", size: "sm", onClick: load, disabled: loading }, loading ? "Refreshing\u2026" : "Refresh")), data.items.length === 0 ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-empty text-muted" }, /* @__PURE__ */ react_default.createElement("p", null, "No images waiting."), /* @__PURE__ */ react_default.createElement("p", null, "In Stash, tag images ", /* @__PURE__ */ react_default.createElement("strong", null, data.tags.queue.name), ", or tick images in any image list and choose ", /* @__PURE__ */ react_default.createElement("strong", null, "\u22EF \u2192 Add to imaglr"), ".")) : /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-grid" }, data.items.map((card) => /* @__PURE__ */ react_default.createElement("button", { key: card.id, type: "button", className: "imaglr-card-button", onClick: () => setEditing(card.id) }, /* @__PURE__ */ react_default.createElement(ItemCard, { card, highlighted: card.id === openId })))), editing ? /* @__PURE__ */ react_default.createElement(
      Editor,
      {
        itemId: editing,
        onClose: (changed) => {
          setEditing(null);
          if (changed) load();
        }
      }
    ) : null);
  }

  // src/ui/sent/SentTab.tsx
  function SentTab() {
    const { Button, Badge } = PluginApi.libraries.Bootstrap;
    const { LoadingIndicator } = PluginApi.components;
    const Toast = PluginApi.hooks.useToast();
    const [items, setItems] = react_default.useState(null);
    const load = react_default.useCallback(() => {
      runOperation("sent_list").then((r) => setItems(r.items), (e) => Toast.error(e));
    }, []);
    react_default.useEffect(load, [load]);
    async function retry(item) {
      try {
        await runOperation("retry_follow_up", { item_id: item.id });
        Toast.success("Done.");
        load();
      } catch (e) {
        Toast.error(e);
      }
    }
    async function alwaysDrop(tag) {
      try {
        await runOperation("tag_map_set", { stash_tag: tag, imaglr_tag: null });
        Toast.success(`"${tag}" won't be suggested again.`);
      } catch (e) {
        Toast.error(e);
      }
    }
    if (!items) return LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, null) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026");
    if (!items.length) return /* @__PURE__ */ react_default.createElement("p", { className: "text-muted imaglr-empty" }, "Nothing sent yet.");
    return /* @__PURE__ */ react_default.createElement("ul", { className: "imaglr-sent" }, items.map((item) => /* @__PURE__ */ react_default.createElement("li", { key: item.id, className: "imaglr-sent-row card" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-sent-thumb" }, item.thumb ? /* @__PURE__ */ react_default.createElement("img", { src: baseUrl() + item.thumb, alt: "", loading: "lazy" }) : null), /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-sent-body" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-card-title" }, item.title, item.files > 1 ? /* @__PURE__ */ react_default.createElement("span", { className: "text-muted" }, " + ", item.files - 1, " more") : null), /* @__PURE__ */ react_default.createElement("div", { className: "small" }, /* @__PURE__ */ react_default.createElement(Badge, { variant: item.sent_as === "publish" ? "success" : "primary" }, SENT_AS_LABELS[item.sent_as]), " ", item.blog ? `on ${item.blog}` : null, " \xB7 ", fmtDate(item.sent_at), " \xB7", " ", /* @__PURE__ */ react_default.createElement("a", { href: imaglrLink(item.sent_as, item.post_url), target: "_blank", rel: "noreferrer" }, item.sent_as === "draft" ? "Open imaglr drafts" : "Open on imaglr")), item.followup_failed ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-warning" }, item.error_detail, " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "link", size: "sm", className: "p-0", onClick: () => retry(item) }, item.action === "publish" ? "Retry publishing" : "Retry adding to queue")) : item.error_detail ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-warning" }, item.error_detail) : null, item.dropped_tags.length ? /* @__PURE__ */ react_default.createElement("div", { className: "small" }, /* @__PURE__ */ react_default.createElement("span", { className: "text-muted" }, "imaglr dropped:"), " ", item.dropped_tags.map((tag) => /* @__PURE__ */ react_default.createElement("span", { key: tag, className: "imaglr-dropped" }, tag, " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "link", size: "sm", className: "p-0", onClick: () => alwaysDrop(tag) }, "Always drop")))) : null))));
  }

  // src/ui/settings/BlogSettings.tsx
  function BlogSettings({ onClose }) {
    const { Modal, Button, Form, Alert, Badge } = PluginApi.libraries.Bootstrap;
    const Toast = PluginApi.hooks.useToast();
    const [blogs, setBlogs] = react_default.useState(null);
    const [key, setKey] = react_default.useState("");
    const [defaultAction, setDefaultAction] = react_default.useState("draft");
    const [adding, setAdding] = react_default.useState(false);
    const [checking, setChecking] = react_default.useState(false);
    const [error, setError] = react_default.useState(null);
    const [changed, setChanged] = react_default.useState(false);
    const check = react_default.useCallback(() => {
      setChecking(true);
      runOperation("blogs_check").then((r) => setBlogs(r.blogs), (e) => Toast.error(e)).finally(() => setChecking(false));
    }, []);
    react_default.useEffect(() => {
      runOperation("blogs_list").then((r) => {
        setBlogs(r.blogs);
        if (r.blogs.length) check();
      }, (e) => Toast.error(e));
    }, [check]);
    async function add(e) {
      e.preventDefault();
      setAdding(true);
      setError(null);
      try {
        await runOperation("blog_add", { api_key: key, default_action: defaultAction });
        setKey("");
        setChanged(true);
        check();
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
    async function remove(blog) {
      if (!window.confirm(`Remove ${blog.label}? Its key is deleted from the plugin. Nothing changes on imaglr.`)) return;
      try {
        setBlogs((await runOperation("blog_remove", { blog_id: blog.id })).blogs);
        setChanged(true);
      } catch (err) {
        Toast.error(err);
      }
    }
    return /* @__PURE__ */ react_default.createElement(Modal, { show: true, onHide: () => onClose(changed), size: "lg", dialogClassName: "imaglr-editor", scrollable: true }, /* @__PURE__ */ react_default.createElement(Modal.Header, { closeButton: true }, /* @__PURE__ */ react_default.createElement(Modal.Title, null, "imaglr blogs")), /* @__PURE__ */ react_default.createElement(Modal.Body, null, blogs === null ? /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026") : null, blogs && blogs.length ? /* @__PURE__ */ react_default.createElement("ul", { className: "imaglr-blog-list" }, blogs.map((blog) => {
      const problem = blogProblem(blog);
      const postsLeft = blog.limits?.posts_per_day?.remaining;
      return /* @__PURE__ */ react_default.createElement("li", { key: blog.id, className: "imaglr-blog" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-blog-name" }, blog.url ? /* @__PURE__ */ react_default.createElement("a", { href: blog.url, target: "_blank", rel: "noreferrer" }, blog.label) : blog.label, " ", problem ? /* @__PURE__ */ react_default.createElement(Badge, { variant: "warning" }, "Needs attention") : blog.ok ? /* @__PURE__ */ react_default.createElement(Badge, { variant: "success" }, "OK") : null), /* @__PURE__ */ react_default.createElement("small", { className: "text-muted" }, "Key ", blog.key_hint, postsLeft != null ? ` \xB7 ${postsLeft} posts left today` : ""), problem ? /* @__PURE__ */ react_default.createElement("div", { className: "small text-warning" }, problem) : null, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-blog-controls" }, /* @__PURE__ */ react_default.createElement(Form.Label, { className: "mb-0", htmlFor: `imaglr-action-${blog.id}` }, "When sent"), /* @__PURE__ */ react_default.createElement(
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
      ), /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "text-danger", onClick: () => remove(blog) }, "Remove")));
    })) : null, blogs && blogs.length ? /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", size: "sm", onClick: check, disabled: checking, className: "mb-3" }, checking ? "Checking with imaglr\u2026" : "Check again") : null, /* @__PURE__ */ react_default.createElement(Form, { onSubmit: add, className: "imaglr-add-blog" }, /* @__PURE__ */ react_default.createElement("h6", null, blogs && blogs.length ? "Add another blog" : "Add your imaglr blog"), /* @__PURE__ */ react_default.createElement("p", { className: "small text-muted" }, "On imaglr, open ", /* @__PURE__ */ react_default.createElement("a", { href: "https://imaglr.com/settings", target: "_blank", rel: "noreferrer" }, "Settings \u2192 API"), " and create a key with the ", /* @__PURE__ */ react_default.createElement("strong", null, "read"), " and ", /* @__PURE__ */ react_default.createElement("strong", null, "manage"), " permissions. Each key belongs to one blog. The key is stored only in this plugin and never shown again."), /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "API key"), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        className: "text-input",
        type: "password",
        autoComplete: "off",
        value: key,
        placeholder: "pbk_\u2026",
        onChange: (e) => setKey(e.target.value)
      }
    )), /* @__PURE__ */ react_default.createElement(Form.Group, null, /* @__PURE__ */ react_default.createElement(Form.Label, null, "When sent, by default"), /* @__PURE__ */ react_default.createElement(
      Form.Control,
      {
        className: "text-input",
        as: "select",
        value: defaultAction,
        onChange: (e) => setDefaultAction(e.target.value)
      },
      Object.keys(ACTION_LABELS).map((a) => /* @__PURE__ */ react_default.createElement("option", { key: a, value: a }, ACTION_LABELS[a]))
    ), /* @__PURE__ */ react_default.createElement(Form.Text, { muted: true }, "You can still choose differently each time you send.")), error ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "danger" }, error) : null, /* @__PURE__ */ react_default.createElement(Button, { type: "submit", variant: "primary", disabled: adding || !key.trim() }, adding ? "Checking the key\u2026" : "Add blog"))));
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
    const { Nav, Tab, Button, Alert } = PluginApi.libraries.Bootstrap;
    const { useHistory, useLocation } = PluginApi.libraries.ReactRouterDOM;
    const { Icon } = PluginApi.components;
    const history = useHistory();
    const params = new URLSearchParams(useLocation().search);
    const openId = params.get("open");
    const requested = params.get("tab");
    const tab = isTab(requested) ? requested : "images";
    const [blogs, setBlogs] = react_default.useState(null);
    const [showBlogs, setShowBlogs] = react_default.useState(false);
    const [reloadKey, setReloadKey] = react_default.useState(0);
    const loadBlogs = react_default.useCallback(() => {
      runOperation("blogs_list").then((r) => setBlogs(r.blogs), () => setBlogs([]));
    }, []);
    react_default.useEffect(loadBlogs, [loadBlogs]);
    react_default.useEffect(() => {
      const previous = document.title;
      document.title = "Post to imaglr | Stash";
      return () => {
        document.title = previous;
      };
    }, []);
    function setTab(key) {
      history.replace({ search: `?tab=${key}` });
    }
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-page container-fluid" }, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-page-header" }, /* @__PURE__ */ react_default.createElement("h2", { className: "imaglr-page-title" }, "Post to imaglr"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", onClick: () => setShowBlogs(true) }, /* @__PURE__ */ react_default.createElement(Icon, { icon: PluginApi.libraries.FontAwesomeSolid.faCog }), " Blogs")), blogs && blogs.length === 0 ? /* @__PURE__ */ react_default.createElement(Alert, { variant: "info", className: "imaglr-welcome" }, /* @__PURE__ */ react_default.createElement("strong", null, "Add your imaglr blog to start."), " You'll need an API key from imaglr (paid supporters only).", " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "primary", size: "sm", onClick: () => setShowBlogs(true) }, "Add blog")) : null, /* @__PURE__ */ react_default.createElement(Tab.Container, { activeKey: tab, onSelect: (key) => key && setTab(key) }, /* @__PURE__ */ react_default.createElement(Nav, { variant: "tabs", className: "imaglr-tabs" }, TABS.map(({ key, title }) => /* @__PURE__ */ react_default.createElement(Nav.Item, { key }, /* @__PURE__ */ react_default.createElement(Nav.Link, { eventKey: key }, title)))), /* @__PURE__ */ react_default.createElement(Tab.Content, { className: "imaglr-tab-content", key: reloadKey }, /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "clips" }, /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Clips are coming next.")), /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "images" }, tab === "images" ? /* @__PURE__ */ react_default.createElement(ImagesTab, { openId }) : null), /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "sent" }, tab === "sent" ? /* @__PURE__ */ react_default.createElement(SentTab, null) : null))), /* @__PURE__ */ react_default.createElement(BackendStatus, null), showBlogs ? /* @__PURE__ */ react_default.createElement(
      BlogSettings,
      {
        onClose: (changed) => {
          setShowBlogs(false);
          if (changed) {
            loadBlogs();
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
})();
