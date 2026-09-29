// SPDX-License-Identifier: AGPL-3.0-only
// Tag chips: active tags go to imaglr; parked ones (removed, or over the limit) can be re-added with a tap.
import React from "react";
import { activate, activeNames, addTag, MAX_TAGS, removeTag } from "../lib/tags.ts";
import type { TagChip } from "../lib/types.ts";

const SOURCE_LABELS: Record<string, string> = {
  marker: "marker",
  scene: "scene",
  performer: "performer",
  studio: "studio",
  image: "image",
  gallery: "gallery",
  manual: "added",
};

interface Props {
  chips: TagChip[];
  lowercase: boolean;
  disabled?: boolean;
  onChange: (chips: TagChip[]) => void;
}

export function TagEditor({ chips, lowercase, disabled, onChange }: Props) {
  const { Button, Form, InputGroup } = PluginApi.libraries.Bootstrap;
  const [text, setText] = React.useState("");
  const [message, setMessage] = React.useState<string | null>(null);
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

  function reactivate(name: string) {
    const result = activate(chips, name);
    if (result.ok) onChange(result.chips);
    else setMessage(result.error);
  }

  const active = chips.filter((c) => c.state === "active");
  const parked = chips.filter((c) => c.state !== "active");

  return (
    <div className="imaglr-tags">
      <div className="imaglr-tags-header">
        <strong>Tags</strong>
        <span className={count > MAX_TAGS ? "text-danger" : "text-muted"}>
          {count} / {MAX_TAGS}
        </span>
      </div>
      <div className="imaglr-chips">
        {active.length === 0 ? <span className="text-muted">No tags yet.</span> : null}
        {active.map((chip) => (
          <span key={chip.name} className="imaglr-chip" title={chip.original ? `from Stash: ${chip.original}` : undefined}>
            {chip.name}
            <small className="imaglr-chip-source">{SOURCE_LABELS[chip.source] ?? chip.source}</small>
            {disabled ? null : (
              <button type="button" className="imaglr-chip-remove" aria-label={`Remove ${chip.name}`}
                onClick={() => onChange(removeTag(chips, chip.name))}>
                ×
              </button>
            )}
          </span>
        ))}
      </div>
      {disabled ? null : (
        <InputGroup className="imaglr-tag-input">
          <Form.Control className="text-input"
            value={text}
            placeholder="Add a tag"
            maxLength={80}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
              setText(e.target.value);
              setMessage(null);
            }}
            onKeyDown={(e: React.KeyboardEvent) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
          <InputGroup.Append>
            <Button variant="secondary" onClick={add} disabled={!text.trim()}>Add</Button>
          </InputGroup.Append>
        </InputGroup>
      )}
      {message ? <div className="small text-warning mt-1">{message}</div> : null}
      {parked.length ? (
        <details className="imaglr-parked">
          <summary className="text-muted">Not included ({parked.length})</summary>
          <div className="imaglr-chips">
            {parked.map((chip) => (
              <button key={chip.name} type="button" className="imaglr-chip imaglr-chip-parked"
                disabled={disabled || chip.state === "too_long"} onClick={() => reactivate(chip.name)}
                title={chip.reason}>
                {chip.state === "too_long" ? chip.name : `+ ${chip.name}`}
                <small className="imaglr-chip-source">{chip.reason}</small>
              </button>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}
