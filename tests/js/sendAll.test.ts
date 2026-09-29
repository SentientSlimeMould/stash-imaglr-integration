// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { summarisePlan, type PlanEntry } from "../../src/ui/lib/sendAll.ts";

const plan: PlanEntry[] = [
  { id: "a", blog: "one", action: "draft", downgraded: true },
  { id: "b", blog: "two", action: "queue" },
  { id: "c", skip: "no_blog", reason: "no blog chosen" },
  { id: "d", skip: "no_blog", reason: "no blog chosen" },
  { id: "e", skip: "busy", reason: "already sending" },
];

test("without a fallback blog, unassigned items are skipped", () => {
  const s = summarisePlan(plan, null);
  assert.deepEqual(s.sending, [["one as drafts", 1], ["two to the queue", 1]]);
  assert.deepEqual(s.skipped, [["no blog chosen", 2], ["already sending", 1]]);
  assert.equal(s.total, 2);
  assert.equal(s.downgraded, 1);
});

test("a fallback blog set to publish sends its items as drafts and counts them as downgraded", () => {
  const s = summarisePlan(plan, { id: 1, label: "one", default_action: "publish" });
  assert.deepEqual(s.sending, [["one as drafts", 3], ["two to the queue", 1]]);
  assert.deepEqual(s.skipped, [["already sending", 1]]);
  assert.equal(s.total, 4);
  assert.equal(s.downgraded, 3);
});
