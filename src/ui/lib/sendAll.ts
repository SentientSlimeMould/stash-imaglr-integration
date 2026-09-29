// SPDX-License-Identifier: AGPL-3.0-only
// Summary for the Send all / Send selected confirmation (src/ui/queue/SendAllDialog.tsx).

export interface PlanEntry {
  id: string;
  blog?: string;
  blog_id?: number;
  action?: "draft" | "queue";
  downgraded?: boolean;
  skip?: string;
  reason?: string;
}

export interface FallbackBlog {
  id: number;
  label: string;
  default_action: "draft" | "queue" | "publish";
}

const ACTION_WORDS = { draft: "as drafts", queue: "to the queue" };

/**
 * What will happen, counting items with no blog as going to `fallback` when one is chosen.
 * Send all never publishes: a Publish-now default becomes a draft ("downgraded").
 */
export function summarisePlan(plan: PlanEntry[], fallback: FallbackBlog | null) {
  const sending = new Map<string, number>();
  const skipped = new Map<string, number>();
  let downgraded = 0;
  let total = 0;
  for (const e of plan) {
    let blog = e.blog;
    let action = e.action;
    let down = !!e.downgraded;
    if (e.skip === "no_blog" && fallback) {
      blog = fallback.label;
      down = fallback.default_action === "publish";
      action = fallback.default_action === "queue" ? "queue" : "draft";
    } else if (e.skip) {
      const reason = e.reason ?? e.skip;
      skipped.set(reason, (skipped.get(reason) ?? 0) + 1);
      continue;
    }
    const key = `${blog} ${ACTION_WORDS[action ?? "draft"]}`;
    sending.set(key, (sending.get(key) ?? 0) + 1);
    if (down) downgraded++;
    total++;
  }
  return { sending: [...sending], skipped: [...skipped], downgraded, total };
}
