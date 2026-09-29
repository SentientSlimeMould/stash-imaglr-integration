// SPDX-License-Identifier: AGPL-3.0-only
// The "Post to imaglr" page. Skeleton: tabs plus a backend status line.
import React from "react";
import { runOperation, type Ping } from "./api.ts";
import { ImagesTab } from "./queue/ImagesTab.tsx";

const TABS = [
  { key: "clips", title: "Clips" },
  { key: "images", title: "Images" },
  { key: "sent", title: "Sent" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function BackendStatus() {
  const [ping, setPing] = React.useState<Ping | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    runOperation<Ping>("ping").then(setPing, (e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="alert alert-danger">Plugin backend not working: {error}</div>;
  if (!ping) return <div className="text-muted small">Checking plugin…</div>;
  return (
    <div className="text-muted small">
      Plugin v{ping.plugin_version} · Stash {ping.stash_version} · Python {ping.python}
    </div>
  );
}

function isTab(key: string | null): key is TabKey {
  return TABS.some((t) => t.key === key);
}

export function PostPage() {
  const { Nav, Tab } = PluginApi.libraries.Bootstrap;
  const { useHistory, useLocation } = PluginApi.libraries.ReactRouterDOM;
  const history = useHistory();
  const params = new URLSearchParams(useLocation().search);
  const openId = params.get("open");
  const requested = params.get("tab");
  const tab: TabKey = isTab(requested) ? requested : "images";

  function setTab(key: TabKey) {
    history.replace({ search: `?tab=${key}` });
  }

  React.useEffect(() => {
    const previous = document.title;
    document.title = "Post to imaglr | Stash";
    return () => {
      document.title = previous;
    };
  }, []);

  return (
    <div className="imaglr-page container-fluid">
      <h2 className="imaglr-page-title">Post to imaglr</h2>
      <Tab.Container activeKey={tab} onSelect={(key: TabKey) => key && setTab(key)}>
        <Nav variant="tabs" className="imaglr-tabs">
          {TABS.map(({ key, title }) => (
            <Nav.Item key={key}>
              <Nav.Link eventKey={key}>{title}</Nav.Link>
            </Nav.Item>
          ))}
        </Nav>
        <Tab.Content className="imaglr-tab-content">
          <Tab.Pane eventKey="clips">
            <p className="text-muted">Clips will appear here.</p>
          </Tab.Pane>
          <Tab.Pane eventKey="images">{tab === "images" ? <ImagesTab openId={openId} /> : null}</Tab.Pane>
          <Tab.Pane eventKey="sent">
            <p className="text-muted">Sent posts will appear here.</p>
          </Tab.Pane>
        </Tab.Content>
      </Tab.Container>
      <BackendStatus />
    </div>
  );
}
