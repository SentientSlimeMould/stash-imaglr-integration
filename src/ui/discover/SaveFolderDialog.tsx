// SPDX-License-Identifier: AGPL-3.0-only
// Where saved posts go: a folder inside one of Stash's libraries that Stash can write to (a library mounted
// read-only can't take saves). Asked the first time you save, when the folder can't be written to, and from the
// plugin's Settings. The backend checks by writing a test file before it accepts a folder.
import React from "react";
import { runOperation } from "../api.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";

export interface SaveSetup {
  enabled: boolean;
  autoplay: boolean;
  quick_save?: boolean;
  folder: string | null;
  folder_ok: boolean; // inside a Stash library
  folder_writable: boolean; // and Stash can write there
  libraries: { path: string; videos: boolean; images: boolean; writable: boolean }[];
}

/** Ready to save into: inside a library and writable. */
export function folderReady(setup: SaveSetup | null): boolean {
  return !!setup && setup.folder_ok && setup.folder_writable;
}

/** Why the current folder won't do, if it won't. */
export function folderProblem(setup: SaveSetup | null): string | null {
  if (!setup?.folder) return null;
  if (!setup.folder_ok) return `${setup.folder} isn't inside one of your Stash libraries any more.`;
  if (!setup.folder_writable) return `Stash can't write to ${setup.folder}. Its library may be read-only.`;
  return null;
}

export function SaveFolderDialog({ setup, onDone, onCancel }: { setup: SaveSetup; onDone: (s: SaveSetup) => void; onCancel: () => void }) {
  const { Form } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const usable = setup.libraries.filter((l) => l.videos && l.images).sort((a, b) => Number(b.writable) - Number(a.writable));
  const suggest = (path: string) => `${path.replace(/[\\/]+$/, "")}${path.includes("\\") ? "\\" : "/"}imaglr`;
  const firstWritable = usable.find((l) => l.writable);
  const [folder, setFolder] = React.useState(folderReady(setup) && setup.folder ? setup.folder : firstWritable ? suggest(firstWritable.path) : setup.folder ?? "");
  const [busy, setBusy] = React.useState(false);
  const problem = folderProblem(setup);
  async function accept() {
    setBusy(true);
    try {
      onDone(await runOperation<SaveSetup>("save_folder_set", { folder }));
    } catch (e) {
      Toast.error(e);
      setBusy(false);
    }
  }
  return (
    <ConfirmDialog title="Where should saved posts go?" accept="Use this folder" busy={busy} disabled={!folder.trim()}
      onAccept={accept} onCancel={onCancel}>
      {problem ? <div className="alert alert-warning">{problem}</div> : null}
      <p>Saved posts go into a folder inside one of your Stash libraries, so Stash adds them like any other file.
        Each creator gets a folder of their own.</p>
      {usable.length > 1 ? (
        <Form.Group>
          <Form.Label>Library</Form.Label>
          <Form.Control as="select" className="text-input" defaultValue={firstWritable?.path}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setFolder(suggest(e.target.value))}>
            {usable.map((l) => <option key={l.path} value={l.path}>{l.path}{l.writable ? "" : " (read-only)"}</option>)}
          </Form.Control>
        </Form.Group>
      ) : null}
      <Form.Group className="mb-0">
        <Form.Label>Folder</Form.Label>
        <Form.Control className="text-input" value={folder}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFolder(e.target.value)} />
        {usable.length === 0 ? (
          <Form.Text className="text-warning">None of your Stash libraries takes both pictures and videos.</Form.Text>
        ) : !firstWritable ? (
          <Form.Text className="text-warning">Stash can't write to any of your libraries. Saving needs one it can write to.</Form.Text>
        ) : null}
      </Form.Group>
    </ConfirmDialog>
  );
}

/** The plugin Settings' "Saving from imaglr" section: where saves go, and Change. */
export function SaveFolderSection() {
  const { Button } = PluginApi.libraries.Bootstrap;
  const [setup, setSetup] = React.useState<SaveSetup | null>(null);
  const [changing, setChanging] = React.useState(false);
  React.useEffect(() => {
    runOperation<SaveSetup>("save_setup").then(setSetup, () => setSetup(null));
  }, []);
  if (!setup?.enabled) return null;
  const problem = folderProblem(setup);
  return (
    <div className="imaglr-settings-section">
      <h5>Saving from imaglr</h5>
      <p className="small text-muted mb-2">
        {setup.folder ? <>Saved posts go to <code>{setup.folder}</code>.</> : "You'll choose where saved posts go the first time you save one."}
      </p>
      {problem ? <div className="alert alert-warning">{problem}</div> : null}
      <Button variant="secondary" onClick={() => setChanging(true)}>{setup.folder ? "Change folder" : "Choose folder"}</Button>
      {changing ? (
        <SaveFolderDialog setup={setup} onCancel={() => setChanging(false)} onDone={(s) => { setSetup(s); setChanging(false); }} />
      ) : null}
    </div>
  );
}
