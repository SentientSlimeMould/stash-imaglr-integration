/* Imaglr Integration for Stash. SPDX-License-Identifier: AGPL-3.0-only
 * Generated from src/ui by scripts/build.mjs. Do not edit. */
"use strict";
(() => {
  // src/ui/shims/react.ts
  var react_default = PluginApi.React;

  // src/ui/routes.ts
  var ROUTE = "/plugins/imaglr-integration";

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
  function PostPage() {
    const { Nav, Tab } = PluginApi.libraries.Bootstrap;
    const [tab, setTab] = react_default.useState("clips");
    react_default.useEffect(() => {
      const previous = document.title;
      document.title = "Post to imaglr | Stash";
      return () => {
        document.title = previous;
      };
    }, []);
    return /* @__PURE__ */ react_default.createElement("div", { className: "imaglr-page container-fluid" }, /* @__PURE__ */ react_default.createElement("h2", { className: "imaglr-page-title" }, "Post to imaglr"), /* @__PURE__ */ react_default.createElement(Tab.Container, { activeKey: tab, onSelect: (key) => key && setTab(key) }, /* @__PURE__ */ react_default.createElement(Nav, { variant: "tabs", className: "imaglr-tabs" }, TABS.map(({ key, title }) => /* @__PURE__ */ react_default.createElement(Nav.Item, { key }, /* @__PURE__ */ react_default.createElement(Nav.Link, { eventKey: key }, title)))), /* @__PURE__ */ react_default.createElement(Tab.Content, { className: "imaglr-tab-content" }, TABS.map(({ key, title }) => /* @__PURE__ */ react_default.createElement(Tab.Pane, { key, eventKey: key }, /* @__PURE__ */ react_default.createElement("p", { className: "text-muted" }, title, " will appear here."))))), /* @__PURE__ */ react_default.createElement(BackendStatus, null));
  }

  // src/ui/index.tsx
  PluginApi.register.route(ROUTE, PostPage);
  PluginApi.patch.before("MainNavBar.MenuItems", (props) => [
    {
      ...props,
      children: /* @__PURE__ */ react_default.createElement(react_default.Fragment, null, props.children, /* @__PURE__ */ react_default.createElement(NavItem, null))
    }
  ]);
})();
