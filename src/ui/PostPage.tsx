// SPDX-License-Identifier: AGPL-3.0-only
// The "Post to imaglr" page: Clips · Images · Sent, plus blog settings. With browsing switched on (the
// plugin's "Browse and save from imaglr" setting), the page is "imaglr" in two sections: Share (those three
// tabs, unchanged) and Discover (Feed · Likes · Explore, see discover/Discover.tsx).
import React from "react";
import { runOperation, type Ping } from "./api.ts";
import type { Blog, QueueResponse } from "./model.ts";
import type { Status } from "./lib/types.ts";
import { QueueTab } from "./queue/QueueTab.tsx";
import { SentTab } from "./sent/SentTab.tsx";
import { Settings } from "./settings/Settings.tsx";
import { Discover, DISCOVER_TABS, type DiscoverTab } from "./discover/Discover.tsx";

const TABS = [
  { key: "clips", title: "Clips" },
  { key: "images", title: "Images" },
  { key: "sent", title: "Sent" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function isTab(key: string | null): key is TabKey {
  return TABS.some((t) => t.key === key);
}

function isDiscoverTab(key: string | null): key is DiscoverTab {
  return DISCOVER_TABS.some((t) => t.key === key);
}

const POLL_MS = 2000;
const BUSY = ["exporting", "sending"];

interface SendStatus {
  items: { id: string; status: Status; progress: number; error_code: string | null; error_detail: string | null }[];
}

/** The queue, fetched once for the whole page: both tabs and the tab counters read from it. */
function useQueue(paused: boolean) {
  const [data, setData] = React.useState<QueueResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0); // bumped after every poll, success or failure, to schedule the next

  const load = React.useCallback(() => {
    return runOperation<QueueResponse>("queue").then((d) => {
      setData(d);
      setError(null);
    }, (e: Error) => setError(e.message)).finally(() => setTick((t) => t + 1));
  }, []);

  // Sends interrupted by a Stash restart are marked failed (and old prepared files cleaned up) first.
  React.useEffect(() => {
    runOperation("recover").catch(() => undefined).finally(load);
  }, [load]);

  // While anything is being sent, keep progress fresh (not while an editor is open) with the light status
  // call; the whole list is fetched again once something finishes. A failed poll just tries again.
  const inFlight = data?.items.some((c) => BUSY.includes(c.status)) ?? false;
  React.useEffect(() => {
    if (!inFlight || paused || !data) return;
    const timer = window.setTimeout(() => {
      runOperation<SendStatus>("send_status").then((s) => {
        const fresh = new Map(s.items.map((i) => [i.id, i]));
        const finished = data.items.some((c) => BUSY.includes(c.status) && !fresh.has(c.id));
        if (finished) return load();
        setData({ ...data, items: data.items.map((c) => (fresh.has(c.id) ? { ...c, ...fresh.get(c.id)! } : c)) });
        setTick((t) => t + 1);
      }, (e: Error) => { setError(e.message); setTick((t) => t + 1); });
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [tick, inFlight, paused, load]);

  return { data, error, load };
}

/** Stash's tab counter: a small pill after the title (ui/v2.5/src/components/Shared/Counter.tsx). */
function TabTitle({ title, count }: { title: string; count: number | undefined }) {
  const { Badge } = PluginApi.libraries.Bootstrap;
  return (
    <>
      {title}
      {count ? <Badge className="left-spacing" pill variant="secondary">{count}</Badge> : null}
    </>
  );
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
  const { Nav, Tab, Button, Alert, ButtonGroup } = PluginApi.libraries.Bootstrap;
  const { useHistory, useLocation } = PluginApi.libraries.ReactRouterDOM;
  const { Icon } = PluginApi.components;
  const history = useHistory();
  const params = new URLSearchParams(useLocation().search);
  const openId = params.get("open");
  const requested = params.get("tab");
  const [browsing, setBrowsing] = React.useState(false); // the Discover section is switched on
  const discoverTab: DiscoverTab | null = browsing && isDiscoverTab(requested) ? requested : null;
  const tab: TabKey = isTab(requested) ? requested : "clips";
  // Discover stays loaded once opened, so going to Share and back keeps your place in the feed.
  const [lastDiscover, setLastDiscover] = React.useState<DiscoverTab | null>(null);
  React.useEffect(() => {
    if (discoverTab) setLastDiscover(discoverTab);
  }, [discoverTab]);
  const [blogs, setBlogs] = React.useState<Blog[] | null>(null);
  const [showBlogs, setShowBlogs] = React.useState(false);
  const [reloadKey, setReloadKey] = React.useState(0);
  const queue = useQueue(!!openId || showBlogs);
  const counts = queue.data && {
    clips: queue.data.items.filter((c) => c.tab === "clips").length,
    images: queue.data.items.filter((c) => c.tab === "images").length,
    sent: queue.data.sent_count,
  };

  const loadBlogs = React.useCallback(() => {
    runOperation<{ blogs: Blog[] }>("blogs_list").then((r) => setBlogs(r.blogs), () => setBlogs([]));
  }, []);
  React.useEffect(loadBlogs, [loadBlogs]);
  React.useEffect(() => {
    runOperation<{ enabled: boolean }>("save_setup").then((s) => setBrowsing(s.enabled), () => setBrowsing(false));
  }, []);

  React.useEffect(() => {
    const previous = document.title;
    document.title = browsing ? "imaglr | Stash" : "Post to imaglr | Stash";
    return () => {
      document.title = previous;
    };
  }, [browsing]);

  function setTab(key: TabKey | DiscoverTab) {
    history.replace({ search: `?tab=${key}` });
  }

  /** Discover's own moves: exploring a tag or creator is a new history entry, so Back returns to the feed. */
  function go(search: Record<string, string>, push = false) {
    const location = { search: `?${new URLSearchParams(search).toString()}` };
    if (push) history.push(location);
    else history.replace(location);
  }

  const shareTabs = (
    <Tab.Container activeKey={tab} onSelect={(key: TabKey) => key && setTab(key)}>
      <Nav variant="tabs" className="imaglr-tabs">
        {TABS.map(({ key, title }) => (
          <Nav.Item key={key}>
            <Nav.Link eventKey={key}><TabTitle title={title} count={counts?.[key]} /></Nav.Link>
          </Nav.Item>
        ))}
      </Nav>
      <Tab.Content className="imaglr-tab-content" key={reloadKey}>
        <Tab.Pane eventKey="clips">{tab === "clips" ? <QueueTab tab="clips" openId={openId} {...queue} /> : null}</Tab.Pane>
        <Tab.Pane eventKey="images">{tab === "images" ? <QueueTab tab="images" openId={openId} {...queue} /> : null}</Tab.Pane>
        <Tab.Pane eventKey="sent">{tab === "sent" ? <SentTab openId={openId} /> : null}</Tab.Pane>
      </Tab.Content>
    </Tab.Container>
  );

  return (
    <div className="imaglr-page container-fluid">
      <div className="imaglr-page-header">
        <h2 className="imaglr-page-title">{browsing ? "imaglr" : "Post to imaglr"}</h2>
        <Button variant="secondary" onClick={() => setShowBlogs(true)}>
          <Icon icon={PluginApi.libraries.FontAwesomeSolid.faCog} /> Settings
        </Button>
      </div>
      {blogs && blogs.length === 0 ? (
        <Alert variant="info" className="imaglr-welcome">
          <strong>Add your imaglr blog to start.</strong> You'll need an API key from imaglr (paid supporters only).{" "}
          <Button variant="primary" size="sm" onClick={() => setShowBlogs(true)}>Open settings</Button>
        </Alert>
      ) : null}
      {browsing ? (
        <ButtonGroup className="imaglr-segmented imaglr-sections">
          <Button variant={discoverTab ? "secondary" : "primary"} onClick={() => setTab(tab)}>Share</Button>
          <Button variant={discoverTab ? "primary" : "secondary"} onClick={() => setTab(discoverTab ?? "feed")}>Discover</Button>
        </ButtonGroup>
      ) : null}
      {lastDiscover || discoverTab ? (
        <div hidden={!discoverTab}>
          <Tab.Container activeKey={discoverTab ?? lastDiscover} onSelect={(key: DiscoverTab) => key && setTab(key)}>
            <Nav variant="tabs" className="imaglr-tabs">
              {DISCOVER_TABS.map(({ key, title }) => (
                <Nav.Item key={key}><Nav.Link eventKey={key}>{title}</Nav.Link></Nav.Item>
              ))}
            </Nav>
            <div className="imaglr-tab-content">
              {blogs ? <Discover tab={(discoverTab ?? lastDiscover)!} params={params} blogs={blogs} go={go} /> : null}
            </div>
          </Tab.Container>
        </div>
      ) : null}
      {discoverTab ? null : shareTabs}
      <BackendStatus />
      {showBlogs ? (
        <Settings
          onClose={(changed) => {
            setShowBlogs(false);
            if (changed) {
              loadBlogs();
              queue.load();
              setReloadKey((k) => k + 1);
            }
          }}
        />
      ) : null}
    </div>
  );
}
