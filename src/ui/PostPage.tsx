// SPDX-License-Identifier: AGPL-3.0-only
// The "Post to imaglr" page. Skeleton: tabs plus a backend status line.
import React from "react";
import { runOperation, type Ping } from "./api.ts";

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

export function PostPage() {
  const { Nav, Tab } = PluginApi.libraries.Bootstrap;
  const [tab, setTab] = React.useState<TabKey>("clips");

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
          {TABS.map(({ key, title }) => (
            <Tab.Pane key={key} eventKey={key}>
              <p className="text-muted">{title} will appear here.</p>
            </Tab.Pane>
          ))}
        </Tab.Content>
      </Tab.Container>
      <BackendStatus />
    </div>
  );
}
