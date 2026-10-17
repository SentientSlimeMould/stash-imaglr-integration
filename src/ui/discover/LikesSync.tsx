// SPDX-License-Identifier: AGPL-3.0-only
// Sync likes, at the top of the Likes tab: save every post you've liked that isn't in your library yet. Started
// by hand, after saying what it does; runs as a Stash task with its progress here and a Stop button; ends with
// what it did. New likes only by default (it stops where an earlier sync got to); "all my likes" goes further.
import React from "react";
import { runOperation } from "../api.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";
import { type SyncState, syncSummary } from "../lib/posts.ts";

const POLL_MS = 3000;

export function LikesSync({ blogId, ready, onNeedFolder, onFinished }: {
  blogId: number | null;
  ready: boolean; // the save folder can take saves
  onNeedFolder: (then: () => void) => void;
  onFinished: () => void;
}) {
  const { Button, Form } = PluginApi.libraries.Bootstrap;
  const { Icon } = PluginApi.components;
  const Toast = PluginApi.hooks.useToast();
  const [sync, setSync] = React.useState<SyncState>({});
  const [asking, setAsking] = React.useState(false);
  const [everything, setEverything] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const wasRunning = React.useRef(false);

  const refresh = React.useCallback(() => runOperation<{ sync: SyncState }>("sync_status").then((r) => setSync(r.sync), () => undefined), []);
  React.useEffect(() => { refresh(); }, [refresh]);
  React.useEffect(() => {
    if (!sync.running) {
      if (wasRunning.current) {
        wasRunning.current = false;
        if (sync.error) Toast.error(syncSummary(sync)); else Toast.success(syncSummary(sync));
        onFinished();
      }
      return;
    }
    wasRunning.current = true;
    const timer = window.setTimeout(refresh, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [sync, refresh]);

  async function start() {
    setBusy(true);
    try {
      setSync((await runOperation<{ sync: SyncState }>("sync_likes", { everything, blog_id: blogId ?? undefined })).sync);
      setAsking(false);
    } catch (e) {
      Toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    try {
      setSync((await runOperation<{ sync: SyncState }>("sync_stop")).sync);
    } catch (e) {
      Toast.error(e);
    }
  }

  return (
    <div className="imaglr-sync">
      {sync.running ? (
        <>
          <span className="small"><span className="spinner-border spinner-border-sm" /> {syncSummary(sync)}</span>
          {sync.phase !== "crediting" ? <Button variant="secondary" size="sm" onClick={stop} disabled={!!(sync as { stop?: boolean }).stop}>Stop</Button> : null}
        </>
      ) : (
        <>
          <Button variant="secondary" onClick={() => (ready ? setAsking(true) : onNeedFolder(() => setAsking(true)))}>
            <Icon icon={PluginApi.libraries.FontAwesomeSolid.faSync} /> Sync likes to your library
          </Button>
          <span className="small text-muted">{syncSummary(sync)}</span>
        </>
      )}
      {asking ? (
        <ConfirmDialog title="Sync your likes" accept="Sync" busy={busy} onAccept={start} onCancel={() => setAsking(false)}>
          <p>Saves every post you've liked that isn't in your library yet, each with its credit, using your import rules
            and exact name matches (there's no review for each post). It runs as a Stash task; you can stop it here.</p>
          <Form.Check id="imaglr-sync-everything" type="checkbox" checked={everything}
            label="Go through all my likes, not just the new ones (slower; finds older likes an earlier sync missed)"
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEverything(e.target.checked)} />
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
