// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtBytes, fmtDate, fmtDims, fmtTime, parseTime, round } from "../../src/ui/lib/format.ts";

test("fmtTime shows minutes, hours and a sign", () => {
  assert.equal(fmtTime(0), "0:00.0");
  assert.equal(fmtTime(62.34), "1:02.3");
  assert.equal(fmtTime(3723.5), "1:02:03.5");
  assert.equal(fmtTime(-5), "-0:05.0");
  assert.equal(fmtTime(65, 0), "1:05");
  assert.equal(fmtTime(null), "–");
  assert.equal(fmtTime(NaN), "–");
});

test("parseTime accepts seconds, m:ss and h:mm:ss", () => {
  assert.equal(parseTime("12.3"), 12.3);
  assert.equal(parseTime(" 1:02.5 "), 62.5);
  assert.equal(parseTime("0:01:02"), 62);
  assert.equal(parseTime(""), null);
  assert.equal(parseTime("1::2"), null);
  assert.equal(parseTime("abc"), null);
  assert.equal(parseTime("-3"), null);
});

test("parseTime round-trips fmtTime", () => {
  assert.equal(parseTime(fmtTime(3723.5)), 3723.5);
});

test("fmtBytes picks a unit", () => {
  assert.equal(fmtBytes(512), "512 B");
  assert.equal(fmtBytes(2048), "2 KB");
  assert.equal(fmtBytes(5 * 1024 * 1024), "5.0 MB");
  assert.equal(fmtBytes(3 * 1024 ** 3), "3.00 GB");
  assert.equal(fmtBytes(null), "–");
});

test("fmtDims needs both sides", () => {
  assert.equal(fmtDims(1920, 1080), "1920×1080");
  assert.equal(fmtDims(1920, null), "–");
  assert.equal(fmtDims(0, 1080), "–");
});

test("fmtDate handles missing and unparseable input", () => {
  assert.equal(fmtDate(null), "–");
  assert.equal(fmtDate("not a date"), "not a date");
  assert.notEqual(fmtDate("2026-01-02T03:04:00Z"), "2026-01-02T03:04:00Z");
});

test("round to places", () => {
  assert.equal(round(1.23456), 1.23);
  assert.equal(round(1.5, 0), 2);
  assert.equal(round(0.125, 1), 0.1);
});
