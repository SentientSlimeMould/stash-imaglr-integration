// SPDX-License-Identifier: AGPL-3.0-only
import { test } from "node:test";
import assert from "node:assert/strict";
import { clampTrim, directMime, pickStream, sameOrigin } from "../../src/ui/lib/clip.ts";

const streams = [
  { url: "http://h/scene/1/stream", mime_type: "video/x-matroska", label: "Direct stream" },
  { url: "http://h/scene/1/stream.mp4?resolution=ORIGINAL", mime_type: "video/mp4", label: "MP4" },
];

test("playable files use the direct stream", () => {
  assert.equal(pickStream("direct", streams, { video_codec: "h264", format: "mp4" }, () => true), "direct");
});

test("HEVC in MKV falls back to Stash's MP4 transcode", () => {
  assert.equal(directMime({ video_codec: "hevc", format: "matroska" }), null);
  assert.equal(pickStream("direct", streams, { video_codec: "hevc", format: "matroska" }, () => true),
    "http://h/scene/1/stream.mp4?resolution=ORIGINAL");
});

test("HEVC in MP4 plays directly only where the browser supports it", () => {
  const info = { video_codec: "hevc", format: "mp4" };
  assert.equal(pickStream("direct", streams, info, (m) => m.includes("hvc1")), "direct");
  assert.notEqual(pickStream("direct", streams, info, () => false), "direct");
});

test("URLs are moved onto this page's origin, keeping path and query", () => {
  assert.equal(sameOrigin("http://0.0.0.0:9999/stash/scene/1/stream?apikey=x", "https://stash.lan"),
    "https://stash.lan/stash/scene/1/stream?apikey=x");
  assert.equal(sameOrigin("/scene/1/stream", "http://127.0.0.1:9931"), "http://127.0.0.1:9931/scene/1/stream");
});

test("trim points stay inside the video and in order", () => {
  assert.deepEqual(clampTrim(-3, 5, 30, "in"), { inS: 0, outS: 5 });
  assert.deepEqual(clampTrim(2, 40, 30, "out"), { inS: 2, outS: 30 });
  assert.deepEqual(clampTrim(6, 5, 30, "in"), { inS: 4.9, outS: 5 });
  assert.deepEqual(clampTrim(6, 5, 30, "out"), { inS: 6, outS: 6.1 });
});
