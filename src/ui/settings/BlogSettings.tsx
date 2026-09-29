// SPDX-License-Identifier: AGPL-3.0-only
// Blogs: one imaglr API key each, kept in the plugin's database and never shown again after saving.
import React from "react";
import { runOperation } from "../api.ts";
import { ACTION_LABELS, blogProblem } from "../lib/send.ts";
import type { Blog, SendAction } from "../model.ts";

export function BlogSettings({ onClose }: { onClose: (changed: boolean) => void }) {
  const { Modal, Button, Form, Alert, Badge } = PluginApi.libraries.Bootstrap;
  const Toast = PluginApi.hooks.useToast();
  const [blogs, setBlogs] = React.useState<Blog[] | null>(null);
  const [key, setKey] = React.useState("");
  const [defaultAction, setDefaultAction] = React.useState<SendAction>("draft");
  const [adding, setAdding] = React.useState(false);
  const [checking, setChecking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [changed, setChanged] = React.useState(false);
  const [rules, setRules] = React.useState<{ stash_tag: string; imaglr_tag: string | null }[]>([]);

  React.useEffect(() => {
    runOperation<{ rules: typeof rules }>("tag_map_list").then((r) => setRules(r.rules), () => undefined);
  }, []);

  const [ruleFrom, setRuleFrom] = React.useState("");
  const [ruleTo, setRuleTo] = React.useState("");

  async function addRule(drop: boolean) {
    try {
      await runOperation("tag_map_set", { stash_tag: ruleFrom, imaglr_tag: drop ? null : ruleTo });
      setRules((await runOperation<{ rules: typeof rules }>("tag_map_list")).rules);
      setRuleFrom("");
      setRuleTo("");
    } catch (err) {
      Toast.error(err);
    }
  }

  async function removeRule(stashTag: string) {
    try {
      setRules((await runOperation<{ rules: typeof rules }>("tag_map_delete", { stash_tag: stashTag })).rules);
    } catch (err) {
      Toast.error(err);
    }
  }

  const check = React.useCallback(() => {
    setChecking(true);
    runOperation<{ blogs: Blog[] }>("blogs_check")
      .then((r) => setBlogs(r.blogs), (e: Error) => Toast.error(e))
      .finally(() => setChecking(false));
  }, []);

  React.useEffect(() => {
    runOperation<{ blogs: Blog[] }>("blogs_list").then((r) => {
      setBlogs(r.blogs);
      if (r.blogs.length) check();
    }, (e: Error) => Toast.error(e));
  }, [check]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setAdding(true);
    setError(null);
    try {
      await runOperation("blog_add", { api_key: key, default_action: defaultAction });
      setKey("");
      setChanged(true);
      check();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAdding(false);
    }
  }

  async function setAction(blog: Blog, action: SendAction) {
    try {
      const r = await runOperation<{ blogs: Blog[] }>("blog_set_action", { blog_id: blog.id, action });
      setBlogs((old) => r.blogs.map((b) => ({ ...b, limits: old?.find((o) => o.id === b.id)?.limits })));
      setChanged(true);
    } catch (err) {
      Toast.error(err);
    }
  }

  async function remove(blog: Blog) {
    if (!window.confirm(`Remove ${blog.label}? Its key is deleted from the plugin. Nothing changes on imaglr.`)) return;
    try {
      setBlogs((await runOperation<{ blogs: Blog[] }>("blog_remove", { blog_id: blog.id })).blogs);
      setChanged(true);
    } catch (err) {
      Toast.error(err);
    }
  }

  return (
    <Modal show onHide={() => undefined} keyboard={false} size="lg" dialogClassName="imaglr-editor" scrollable>
      <Modal.Header>
        <Modal.Title>imaglr blogs</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {blogs === null ? <p className="text-muted">Loading…</p> : null}
        {blogs && blogs.length ? (
          <ul className="imaglr-blog-list">
            {blogs.map((blog) => {
              const problem = blogProblem(blog);
              const postsLeft = blog.limits?.posts_per_day?.remaining;
              return (
                <li key={blog.id} className="imaglr-blog">
                  <div className="imaglr-blog-name">
                    {blog.url ? <a href={blog.url} target="_blank" rel="noreferrer">{blog.label}</a> : blog.label}{" "}
                    {problem ? <Badge variant="warning">Needs attention</Badge> : blog.ok ? <Badge variant="success">OK</Badge> : null}
                  </div>
                  <small className="text-muted">
                    Key {blog.key_hint}
                    {postsLeft != null ? ` · ${postsLeft} posts left today` : ""}
                  </small>
                  {problem ? <div className="small text-warning">{problem}</div> : null}
                  <div className="imaglr-blog-controls">
                    <Form.Label className="mb-0" htmlFor={`imaglr-action-${blog.id}`}>When sent</Form.Label>
                    <Form.Control id={`imaglr-action-${blog.id}`} as="select" size="sm" className="text-input" value={blog.default_action}
                      onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setAction(blog, e.target.value as SendAction)}>
                      {(Object.keys(ACTION_LABELS) as SendAction[]).map((a) => (
                        <option key={a} value={a}>{ACTION_LABELS[a]}</option>
                      ))}
                    </Form.Control>
                    <Button variant="link" className="text-danger" onClick={() => remove(blog)}>Remove</Button>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : null}
        {blogs && blogs.length ? (
          <Button variant="secondary" size="sm" onClick={check} disabled={checking} className="mb-3">
            {checking ? "Checking with imaglr…" : "Check again"}
          </Button>
        ) : null}

        <div className="imaglr-add-blog">
          <h6>Tag rules</h6>
          <p className="small text-muted">
            When a Stash tag is suggested for imaglr, always send it under another name, or never suggest it.
          </p>
          {rules.length === 0 ? null : (
            <ul className="imaglr-rules">
              {rules.map((r) => (
                <li key={r.stash_tag}>
                  <span>
                    <strong>{r.stash_tag}</strong> → {r.imaglr_tag ? <strong>{r.imaglr_tag}</strong> : <em>always dropped</em>}
                  </span>
                  <Button variant="link" className="text-danger p-0" onClick={() => removeRule(r.stash_tag)}>Remove</Button>
                </li>
              ))}
            </ul>
          )}
          <div className="imaglr-rule-form">
            <Form.Control className="text-input" value={ruleFrom} placeholder="Stash tag" aria-label="Stash tag"
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setRuleFrom(e.target.value)} />
            <Form.Control className="text-input" value={ruleTo} placeholder="send as… (imaglr tag)" maxLength={64}
              aria-label="imaglr tag" onChange={(e: React.ChangeEvent<HTMLInputElement>) => setRuleTo(e.target.value)} />
            <Button variant="secondary" disabled={!ruleFrom.trim() || !ruleTo.trim()} onClick={() => addRule(false)}>Add rule</Button>
            <Button variant="secondary" disabled={!ruleFrom.trim()} onClick={() => addRule(true)}>Never suggest</Button>
          </div>
        </div>

        <Form onSubmit={add} className="imaglr-add-blog">
          <h6>{blogs && blogs.length ? "Add another blog" : "Add your imaglr blog"}</h6>
          <p className="small text-muted">
            On imaglr, open <a href="https://imaglr.com/settings" target="_blank" rel="noreferrer">Settings → API</a> and
            create a key with the <strong>read</strong> and <strong>manage</strong> permissions. Each key belongs to one
            blog. The key is stored only in this plugin and never shown again.
          </p>
          <Form.Group>
            <Form.Label>API key</Form.Label>
            <Form.Control className="text-input" type="password" autoComplete="off" value={key} placeholder="pbk_…"
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setKey(e.target.value)} />
          </Form.Group>
          <Form.Group>
            <Form.Label>When sent, by default</Form.Label>
            <Form.Control className="text-input" as="select" value={defaultAction}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setDefaultAction(e.target.value as SendAction)}>
              {(Object.keys(ACTION_LABELS) as SendAction[]).map((a) => (
                <option key={a} value={a}>{ACTION_LABELS[a]}</option>
              ))}
            </Form.Control>
            <Form.Text muted>You can still choose differently each time you send.</Form.Text>
          </Form.Group>
          {error ? <Alert variant="danger">{error}</Alert> : null}
          <Button type="submit" variant="primary" disabled={adding || !key.trim()}>
            {adding ? "Checking the key…" : "Add blog"}
          </Button>
        </Form>
      </Modal.Body>
      <Modal.Footer>
        <Button variant="primary" onClick={() => onClose(changed)}>Close</Button>
      </Modal.Footer>
    </Modal>
  );
}
