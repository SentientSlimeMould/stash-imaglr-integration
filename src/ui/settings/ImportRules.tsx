// SPDX-License-Identifier: AGPL-3.0-only
// Import rules: what an imaglr tag becomes in Stash when you save a post, as remembered from the save review.
// Shown once browsing is switched on. Rules are made in the review; here you see and remove them.
import React from "react";
import { runOperation } from "../api.ts";
import { ConfirmDialog } from "../ConfirmDialog.tsx";
import { type Target, TargetBadge } from "../discover/ReviewDialog.tsx";

interface Rule {
  imaglr_tag: string;
  targets: Target[];
}

export function ImportRules() {
  const { Button } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const [rules, setRules] = React.useState<Rule[] | null>(null);
  const [enabled, setEnabled] = React.useState(false);
  const [removing, setRemoving] = React.useState<string | null>(null);

  React.useEffect(() => {
    runOperation<{ rules: Rule[]; enabled: boolean }>("import_rule_list").then((r) => {
      setRules(r.rules);
      setEnabled(r.enabled);
    }, () => undefined);
  }, []);

  async function remove(tag: string) {
    try {
      setRules((await runOperation<{ rules: Rule[] }>("import_rule_delete", { imaglr_tag: tag })).rules);
    } catch (e) {
      Toast.error(e);
    }
    setRemoving(null);
  }

  if (!enabled && !rules?.length) return null;
  return (
    <div className="imaglr-settings-section">
      <h5>Import rules</h5>
      <p className="small text-muted">
        When you save a post from imaglr, these imaglr tags become these Stash tags, performers or studio. Tick
        Remember in the save review to add one.
      </p>
      {rules?.length ? (
        <ul className="imaglr-rules">
          {rules.map((r) => (
            <li key={r.imaglr_tag}>
              <div>
                <strong>#{r.imaglr_tag}</strong> →{" "}
                {r.targets.length ? r.targets.map((t) => <TargetBadge key={`${t.kind}${t.id}`} target={t} />) : <em>always left out</em>}
              </div>
              <div className="imaglr-rule-actions">
                <Button variant="link" className="text-danger p-0 imaglr-touch" onClick={() => setRemoving(r.imaglr_tag)}>Remove</Button>
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="small text-muted">None yet.</p>}
      {removing ? (
        <ConfirmDialog title={`Remove the rule for "#${removing}"`} accept="Remove" variant="danger"
          onAccept={() => remove(removing)} onCancel={() => setRemoving(null)}>
          "#{removing}" goes back to matching Stash names and aliases when you save.
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
