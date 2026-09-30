// SPDX-License-Identifier: AGPL-3.0-only
// Tag rules: whenever a Stash tag is suggested for imaglr, send these imaglr tags instead (or none).
import React from "react";
import { runOperation } from "../api.ts";
import { TagInput } from "../editor/TagField.tsx";
import { ConfirmDialog } from "../ConfirmDialog.tsx";

interface Rule {
  stash_tag: string;
  imaglr_tags: string[];
}

/** Pick one existing Stash tag, with the same look as Stash's selects. */
function StashTagPicker({ value, onChange }: { value: string | null; onChange: (tag: string | null) => void }) {
  const Select = PluginApi.libraries.ReactSelect.default;
  const [input, setInput] = React.useState("");
  const [found, setFound] = React.useState<string[]>([]);
  React.useEffect(() => {
    if (!input.trim()) {
      setFound([]);
      return;
    }
    const timer = window.setTimeout(() => {
      runOperation<{ tags: string[] }>("stash_tags_find", { q: input }).then((r) => setFound(r.tags), () => setFound([]));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [input]);
  return (
    <Select
      inputId="imaglr-rule-stash-tag"
      className="react-select tag-select"
      classNamePrefix="react-select"
      isClearable
      value={value ? { value, label: value } : null}
      options={found.map((t) => ({ value: t, label: t }))}
      inputValue={input}
      onInputChange={(v: string, meta: { action: string }) => meta.action === "input-change" && setInput(v)}
      onChange={(o: { value: string } | null) => { onChange(o?.value ?? null); setInput(""); }}
      filterOption={() => true}
      placeholder="Choose a Stash tag…"
      noOptionsMessage={() => (input.trim() ? "No Stash tag with that name" : null)}
      styles={{ option: (base: object) => ({ ...base, color: "#000" }) }}
      components={{ IndicatorSeparator: () => null }}
    />
  );
}

export function TagRules() {
  const { Button, Badge, Form } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const [rules, setRules] = React.useState<Rule[]>([]);
  const [stashTag, setStashTag] = React.useState<string | null>(null);
  const [targets, setTargets] = React.useState<string[]>([]);
  const [lowercase, setLowercase] = React.useState(true);

  React.useEffect(() => {
    runOperation<{ rules: Rule[]; lowercase_tags: boolean }>("tag_rule_list").then((r) => {
      setRules(r.rules);
      setLowercase(r.lowercase_tags);
    }, () => undefined);
  }, []);

  async function save(tags: string[]) {
    try {
      setRules((await runOperation<{ rules: Rule[] }>("tag_rule_set", { stash_tag: stashTag, imaglr_tags: tags })).rules);
      setStashTag(null);
      setTargets([]);
    } catch (e) {
      Toast.error(e);
    }
  }

  const [removing, setRemoving] = React.useState<string | null>(null);

  async function remove(tag: string) {
    try {
      setRules((await runOperation<{ rules: Rule[] }>("tag_rule_delete", { stash_tag: tag })).rules);
    } catch (e) {
      Toast.error(e);
    }
    setRemoving(null);
  }

  return (
    <div className="imaglr-settings-section">
      <h5>Tag rules</h5>
      <p className="small text-muted">
        Whenever a Stash tag is suggested for imaglr, send these imaglr tags instead. Include the original if you still
        want it. A rule with no imaglr tags means the Stash tag is never suggested.
      </p>
      {rules.length ? (
        <ul className="imaglr-rules">
          {rules.map((r) => (
            <li key={r.stash_tag}>
              <div>
                <strong>{r.stash_tag}</strong> →{" "}
                {r.imaglr_tags.length
                  ? r.imaglr_tags.map((t) => <Badge key={t} variant="secondary" className="tag-item">{t}</Badge>)
                  : <em>never suggested</em>}
              </div>
              <div className="imaglr-rule-actions">
                <Button variant="link" className="p-0 imaglr-touch" onClick={() => { setStashTag(r.stash_tag); setTargets(r.imaglr_tags); }}>Edit</Button>
                <Button variant="link" className="text-danger p-0 imaglr-touch" onClick={() => setRemoving(r.stash_tag)}>Remove</Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      <Form.Group>
        <Form.Label htmlFor="imaglr-rule-stash-tag">Stash tag</Form.Label>
        <StashTagPicker value={stashTag} onChange={setStashTag} />
      </Form.Group>
      <Form.Group>
        <Form.Label htmlFor="imaglr-rule-targets">Send as (imaglr tags)</Form.Label>
        <TagInput inputId="imaglr-rule-targets" tags={targets} lowercase={lowercase} onChange={setTargets}
          placeholder="Add imaglr tags…" />
      </Form.Group>
      <div className="imaglr-rule-buttons">
        <Button variant="primary" disabled={!stashTag || !targets.length} onClick={() => save(targets)}>Save rule</Button>
        <Button variant="secondary" disabled={!stashTag} onClick={() => save([])}>Never suggest</Button>
      </div>
      {removing ? (
        <ConfirmDialog title={`Remove the rule for "${removing}"`} accept="Remove" variant="danger"
          onAccept={() => remove(removing)} onCancel={() => setRemoving(null)}>
          The Stash tag "{removing}" goes back to being suggested as it is.
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
