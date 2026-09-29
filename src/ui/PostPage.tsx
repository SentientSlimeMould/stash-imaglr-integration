// SPDX-License-Identifier: AGPL-3.0-only
// The "Post to imaglr" page: Clips · Images · Sent, plus blog settings.
import React from "react";
import { runOperation, type Ping } from "./api.ts";
import type { Blog } from "./model.ts";
import { QueueTab } from "./queue/QueueTab.tsx";
import { SentTab } from "./sent/SentTab.tsx";
import { BlogSettings } from "./settings/BlogSettings.tsx";

const TABS = [
  { key: "clips", title: "Clips" },
  { key: "images", title: "Images" },
  { key: "sent", title: "Sent" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function isTab(key: string | null): key is TabKey {
  return TABS.some((t) => t.key === key);
}

function BackendStatus() {
  const [ping, setPing] = React.useState<Ping | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    runOperation<Ping>("ping").then(setPing, (e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="alert alert-danger">The plugin's backend isn't working: {error}</div>;
  if (!ping) return null;
  return (
    <div className="imaglr-footer text-muted small">
      Imaglr Integration v{ping.plugin_version} · Stash {ping.stash_version}
    </div>
  );
}

export function PostPage() {
  const { Nav, Tab, Button, Alert } = PluginApi.libraries.Bootstrap;
  const { useHistory, useLocation } = PluginApi.libraries.ReactRouterDOM;
  const { Icon } = PluginApi.components;
  const history = useHistory();
  const params = new URLSearchParams(useLocation().search);
  const openId = params.get("open");
  const requested = params.get("tab");
  const tab: TabKey = isTab(requested) ? requested : "clips";
  const [blogs, setBlogs] = React.useState<Blog[] | null>(null);
  const [showBlogs, setShowBlogs] = React.useState(false);
  const [reloadKey, setReloadKey] = React.useState(0);

  const loadBlogs = React.useCallback(() => {
    runOperation<{ blogs: Blog[] }>("blogs_list").then((r) => setBlogs(r.blogs), () => setBlogs([]));
  }, []);
  React.useEffect(loadBlogs, [loadBlogs]);

  React.useEffect(() => {
    const previous = document.title;
    document.title = "Post to imaglr | Stash";
    return () => {
      document.title = previous;
    };
  }, []);

  function setTab(key: TabKey) {
    history.replace({ search: `?tab=${key}` });
  }

  return (
    <div className="imaglr-page container-fluid">
      <div className="imaglr-page-header">
        <h2 className="imaglr-page-title">Post to imaglr</h2>
        <Button variant="secondary" onClick={() => setShowBlogs(true)}>
          <Icon icon={PluginApi.libraries.FontAwesomeSolid.faCog} /> Blogs
        </Button>
      </div>
      {blogs && blogs.length === 0 ? (
        <Alert variant="info" className="imaglr-welcome">
          <strong>Add your imaglr blog to start.</strong> You'll need an API key from imaglr (paid supporters only).{" "}
          <Button variant="primary" size="sm" onClick={() => setShowBlogs(true)}>Add blog</Button>
        </Alert>
      ) : null}
      <Tab.Container activeKey={tab} onSelect={(key: TabKey) => key && setTab(key)}>
        <Nav variant="tabs" className="imaglr-tabs">
          {TABS.map(({ key, title }) => (
            <Nav.Item key={key}>
              <Nav.Link eventKey={key}>{title}</Nav.Link>
            </Nav.Item>
          ))}
        </Nav>
        <Tab.Content className="imaglr-tab-content" key={reloadKey}>
          <Tab.Pane eventKey="clips">{tab === "clips" ? <QueueTab tab="clips" openId={openId} /> : null}</Tab.Pane>
          <Tab.Pane eventKey="images">{tab === "images" ? <QueueTab tab="images" openId={openId} /> : null}</Tab.Pane>
          <Tab.Pane eventKey="sent">{tab === "sent" ? <SentTab /> : null}</Tab.Pane>
        </Tab.Content>
      </Tab.Container>
      <BackendStatus />
      {showBlogs ? (
        <BlogSettings
          onClose={(changed) => {
            setShowBlogs(false);
            if (changed) {
              loadBlogs();
              setReloadKey((k) => k + 1);
            }
          }}
        />
      ) : null}
    </div>
  );
}
