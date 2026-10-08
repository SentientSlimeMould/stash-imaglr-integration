// SPDX-License-Identifier: AGPL-3.0-only
// A collapsed section of the editor: a link-style toggle (thumb-sized) with a summary of what is set inside
// while it is closed, and react-bootstrap's Collapse, as Stash's own expandable sections are built. Whether it
// is open is remembered on this device.
import React from "react";

interface Props {
  id: string; // also the localStorage key
  label: string;
  summary?: string; // what is set inside, shown while collapsed; empty when everything is default
  children: React.ReactNode;
}

function load(id: string): boolean {
  try { return localStorage.getItem(`imaglr-fold-${id}`) === "1"; } catch { return false; }
}

function save(id: string, open: boolean): void {
  try { localStorage.setItem(`imaglr-fold-${id}`, open ? "1" : "0"); } catch { /* ignore */ }
}

export function Fold({ id, label, summary, children }: Props) {
  const { Button, Collapse } = PluginApi.libraries.Bootstrap;
  const [open, setOpen] = React.useState(() => load(id));
  return (
    <div className="imaglr-fold">
      <Button variant="link" className="p-0 imaglr-touch" aria-expanded={open} aria-controls={`imaglr-fold-${id}`}
        onClick={() => { setOpen(!open); save(id, !open); }}>
        {open ? "▾" : "▸"} {label}
        {!open && summary ? <span className="text-muted"> · {summary}</span> : null}
      </Button>
      <Collapse in={open}>
        <div id={`imaglr-fold-${id}`}>{children}</div>
      </Collapse>
    </div>
  );
}
