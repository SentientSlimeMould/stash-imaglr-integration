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

  // src/ui/lib/format.ts
  function fmtDims(w, h) {
    return w && h ? `${w}\xD7${h}` : "\u2013";
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
  function ImagesTab({ openId }) {
    const { Button } = PluginApi.libraries.Bootstrap;
    const { LoadingIndicator } = PluginApi.components;
    const [data, setData] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    const [loading, setLoading] = react_default.useState(false);
    const load = react_default.useCallback(() => {
      setLoading(true);
      runOperation("images_queue").then((d) => {
        setData(d);
        setError(null);
      }, (e) => setError(e.message)).finally(() => setLoading(false));
    }, []);
    react_default.useEffect(load, [load]);
    if (error) {
      return /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-danger" }, "Couldn't load the queue: ", error, " ", /* @__PURE__ */ react_default.createElement(Button, { variant: "link", className: "p-0", onClick: load }, "Try again"));
    }
    if (!data) return LoadingIndicator ? /* @__PURE__ */ react_default.createElement(LoadingIndicator, null) : /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Loading\u2026");
    return /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-toolbar" }, /* @__PURE__ */ react_default.createElement("span", { className: "text-muted" }, data.items.length, " ", data.items.length === 1 ? "item" : "items"), /* @__PURE__ */ react_default.createElement(Button, { variant: "secondary", size: "sm", onClick: load, disabled: loading }, loading ? "Refreshing\u2026" : "Refresh")), data.items.length === 0 ? /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-empty text-muted" }, /* @__PURE__ */ react_default.createElement("p", null, "No images waiting."), /* @__PURE__ */ react_default.createElement("p", null, "In Stash, tag images ", /* @__PURE__ */ react_default.createElement("strong", null, data.tags.queue.name), ", or tick images in any image list and choose ", /* @__PURE__ */ react_default.createElement("strong", null, "\u22EF \u2192 Add to imaglr"), ".")) : /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-grid" }, data.items.map((card) => /* @__PURE__ */ react_default.createElement(ItemCard, { key: card.id, card, highlighted: card.id === openId }))));
  }

  // src/ui/PostPage.tsx
  var TABS = [
    { key: "clips", title: "Clips" },
    { key: "images", title: "Images" },
    { key: "sent", title: "Sent" }
  ];
  function BackendStatus() {
    const [ping, setPing] = react_default.useState(null);
    const [error, setError] = react_default.useState(null);
    react_default.useEffect(() => {
      runOperation("ping").then(setPing, (e) => setError(e.message));
    }, []);
    if (error) return /* @__PURE__ */ react_default.createElement("div", { className: "alert alert-danger" }, "Plugin backend not working: ", error);
    if (!ping) return /* @__PURE__ */ react_default.createElement("div", { className: "text-muted small" }, "Checking plugin\u2026");
    return /* @__PURE__ */ react_default.createElement("div", { className: "text-muted small" }, "Plugin v", ping.plugin_version, " \xB7 Stash ", ping.stash_version, " \xB7 Python ", ping.python);
  }
  function isTab(key) {
    return TABS.some((t) => t.key === key);
  }
  function PostPage() {
    const { Nav, Tab } = PluginApi.libraries.Bootstrap;
    const { useHistory, useLocation } = PluginApi.libraries.ReactRouterDOM;
    const history = useHistory();
    const params = new URLSearchParams(useLocation().search);
    const openId = params.get("open");
    const requested = params.get("tab");
    const tab = isTab(requested) ? requested : "images";
    function setTab(key) {
      history.replace({ search: `?tab=${key}` });
    }
    react_default.useEffect(() => {
      const previous = document.title;
      document.title = "Post to imaglr | Stash";
      return () => {
        document.title = previous;
      };
    }, []);
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-page container-fluid" }, /* @__PURE__ */ react_default.createElement("h2", { className: "imaglr-page-title" }, "Post to imaglr"), /* @__PURE__ */ react_default.createElement(Tab.Container, { activeKey: tab, onSelect: (key) => key && setTab(key) }, /* @__PURE__ */ react_default.createElement(Nav, { variant: "tabs", className: "imaglr-tabs" }, TABS.map(({ key, title }) => /* @__PURE__ */ react_default.createElement(Nav.Item, { key }, /* @__PURE__ */ react_default.createElement(Nav.Link, { eventKey: key }, title)))), /* @__PURE__ */ react_default.createElement(Tab.Content, { className: "imaglr-tab-content" }, /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "clips" }, /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Clips will appear here.")), /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "images" }, tab === "images" ? /* @__PURE__ */ react_default.createElement(ImagesTab, { openId }) : null), /* @__PURE__ */ react_default.createElement(Tab.Pane, { eventKey: "sent" }, /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, "Sent posts will appear here.")))), /* @__PURE__ */ react_default.createElement(BackendStatus, null));
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
