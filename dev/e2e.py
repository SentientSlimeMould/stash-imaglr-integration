#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""End-to-end smoke test against a running test Stash and the fake imaglr (see dev/README.md; CI runs it too).

    python3 dev/e2e.py 9931 [fake-imaglr port]

Expects `dev/seed.py <port> setup` and `dev/seed.py <port> saving` to have run. Through the plugin's own
operations it adds a blog, sends one image and one clip (the clip exercises ffmpeg inside the Stash container),
checks both arrive at the fake imaglr, that the Stash tags were swapped, and that the Sent tab lists them. Then it
browses the fake imaglr, saves a post with several files and a reblog into the /saved library, checks the credit
Stash holds, that a saved file is refused for sending, and reblogs it instead. Standard library only.
"""

import json
import sys
import time
import urllib.request

from seed import Stash

QUEUE_TAG, SENT_TAG = "imaglr", "imaglr-sent"


class Plugin:
    def __init__(self, stash):
        self.stash = stash

    def op(self, mode, **args):
        data = self.stash.gql(
            'mutation($a: Map) { runPluginOperation(plugin_id: "imaglrIntegration", args: $a) }',
            a={"mode": mode, **args},
        )
        return data["runPluginOperation"]

    def wait_sent(self, item_id, timeout=240):
        """Poll the queue until the item leaves it as sent (or fails)."""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            cards = {c["id"]: c for c in self.op("queue")["items"]}
            card = cards.get(item_id)
            if card is None:
                detail = self.op("sent_detail", item_id=item_id)["item"]
                return detail
            if card["status"] != last:
                print(f"    {item_id}: {card['status']} {card.get('error_detail') or ''}".rstrip())
                last = card["status"]
            if card["status"] == "failed":
                sys.exit(f"send failed: {card['error_code']}: {card['error_detail']}")
            time.sleep(2)
        sys.exit(f"{item_id} was not sent within {timeout} s")


def check(cond, what):
    print(f"  {'ok' if cond else 'FAIL'}: {what}")
    if not cond:
        sys.exit(1)


def main(port, fake_port):
    stash = Stash(port)
    stash.wait_until_up()
    stash.gql("mutation { reloadPlugins }")
    plugin = Plugin(stash)

    print("plugin")
    ping = plugin.op("ping")
    check(ping.get("ffmpeg"), f"ping: plugin {ping.get('plugin_version')}, Stash {ping.get('stash_version')}, ffmpeg {ping.get('ffmpeg')}")

    print("blog")
    for b in plugin.op("blogs_list")["blogs"]:
        plugin.op("blog_remove", blog_id=b["id"])
    blog = plugin.op("blog_add", api_key="pbk_blogone|e2e-smoke-test-key")["blog"]
    check(blog["label"] == "blog-one" and blog["ok"], f"added {blog['label']}")

    print("queue an image and a clip")
    tags = {t["name"]: t["id"] for t in stash.gql("{ findTags(filter: {per_page: 200}) { tags { id name } } }")["findTags"]["tags"]}
    # An image not sent before (re-runs against the same instance), preferably one not queued either.
    # (from the test media only: posts saved from imaglr into /saved are never sent, by design)
    images = stash.gql("{ findImages(image_filter: {path: {value: \"/data/\", modifier: INCLUDES}}, filter: {per_page: 50, sort: \"path\"}) "
                       "{ images { id title tags { name } } } }")["findImages"]["images"]
    check(images, "Stash has images")
    # Not one already grouped into a post by an earlier run (its card would be the post's), and preferably one
    # never sent; when every image was sent by an earlier run, recycle one by taking its sent tag off.
    grouped = {m.get("stash_image_id") for c in plugin.op("queue")["items"] if c["kind"] == "set" for m in c["members"]}
    candidates = [i for i in images if i["id"] not in grouped] or images
    unsent = [i for i in candidates if SENT_TAG not in {t["name"] for t in i["tags"]}]
    if unsent:
        images = sorted(unsent, key=lambda i: QUEUE_TAG in {t["name"] for t in i["tags"]})
    else:
        stash.gql("mutation($ids: [ID!], $t: [ID!]) { bulkImageUpdate(input: {ids: $ids, tag_ids: {ids: $t, mode: REMOVE}}) { id } }",
                  ids=[candidates[0]["id"]], t=[tags[SENT_TAG]])
        images = [candidates[0]]
    plugin.op("add_images", image_ids=[images[0]["id"]], as_one_post=False)
    tags = {t["name"]: t["id"] for t in stash.gql("{ findTags(filter: {per_page: 200}) { tags { id name } } }")["findTags"]["tags"]}
    check(QUEUE_TAG in tags, f'"{QUEUE_TAG}" tag exists in Stash')
    markers = stash.gql("{ findSceneMarkers(filter: {per_page: 50}) { scene_markers { id title primary_tag { name } tags { id name } } } }")["findSceneMarkers"]["scene_markers"]
    check(markers, "Stash has markers")
    marker = [m for m in markers if SENT_TAG not in {m["primary_tag"]["name"]} | {t["name"] for t in m["tags"]}]
    if not marker:  # recycle one whose sent tag is secondary
        m = next(m for m in markers if m["primary_tag"]["name"] != SENT_TAG)
        stash.gql("mutation($id: ID!, $tags: [ID!]) { sceneMarkerUpdate(input: {id: $id, tag_ids: $tags}) { id } }",
                  id=m["id"], tags=[t["id"] for t in m["tags"] if t["name"] != SENT_TAG])
        m["tags"] = [t for t in m["tags"] if t["name"] != SENT_TAG]
        marker = [m]
    stash.gql(
        "mutation($id: ID!, $tags: [ID!]) { sceneMarkerUpdate(input: {id: $id, tag_ids: $tags}) { id } }",
        id=marker[0]["id"], tags=list({t["id"] for t in marker[0]["tags"]} | {tags[QUEUE_TAG]}),
    )
    queue = plugin.op("queue")["items"]
    image_item = next(c for c in queue if c["kind"] == "image" and c.get("stash_image_id") == images[0]["id"])
    clip_item = next(c for c in queue if c["kind"] == "clip" and c.get("stash_marker_id") == marker[0]["id"])
    check(image_item and clip_item, f"queue shows the image ({image_item['id']}) and the clip ({clip_item['id']})")

    print("send")
    plugin.op("item_update", item_id=image_item["id"], changes={"caption": "e2e caption", "tags": ["e2e", "smoke"]})
    plugin.op("send", item_id=image_item["id"], blog_id=blog["id"], action="draft")
    sent_image = plugin.wait_sent(image_item["id"])
    check(sent_image["sent_as"] == "draft" and sent_image["draft_id"], f"image sent as draft {sent_image['draft_id']}")
    plugin.op("send", item_id=clip_item["id"], blog_id=blog["id"], action="queue")
    sent_clip = plugin.wait_sent(clip_item["id"])
    check(sent_clip["sent_as"] == "queue" and sent_clip["draft_id"], f"clip sent and queued, draft {sent_clip['draft_id']}")

    print("verify")
    page = urllib.request.urlopen(f"http://127.0.0.1:{fake_port}/", timeout=10).read().decode()
    check(sent_image["draft_id"] in page and sent_clip["draft_id"] in page, "fake imaglr lists both drafts")
    clip_row = page[page.index(f"<td>{sent_clip['draft_id']}</td>"):].split("</tr>", 1)[0]
    check("(chunked)" in clip_row, "the clip (over the dev single-request limit) went up in pieces")
    image_row = page[page.index(f"<td>{sent_image['draft_id']}</td>"):].split("</tr>", 1)[0]
    check("(chunked)" not in image_row, "the small image went in one request")
    check("e2e, smoke" in page or "e2e" in page, "tags reached imaglr")
    image_tags = {t["name"] for t in stash.gql(
        "query($id: ID!) { findImage(id: $id) { tags { name } } }", id=images[0]["id"])["findImage"]["tags"]}
    check(SENT_TAG in image_tags and QUEUE_TAG not in image_tags, f"image tags swapped to {SENT_TAG}")
    m = stash.gql("query($ids: [ID!]) { findSceneMarkers(ids: $ids) { scene_markers { primary_tag { name } tags { name } } } }",
                  ids=[marker[0]["id"]])["findSceneMarkers"]["scene_markers"][0]
    marker_tags = {m["primary_tag"]["name"]} | {t["name"] for t in m["tags"]}
    check(SENT_TAG in marker_tags and QUEUE_TAG not in marker_tags, f"marker tags swapped to {SENT_TAG}")
    listed = plugin.op("sent_list", page=1, per_page=10)
    check({sent_image["id"], sent_clip["id"]} <= {i["id"] for i in listed["items"]}, f"Sent tab lists both ({listed['total']} total)")

    print("share a whole scene (no marker)")
    scenes = stash.gql("{ findScenes(scene_filter: {path: {value: \"/data/\", modifier: INCLUDES}}, filter: {per_page: 50, sort: \"path\"}) "
                       "{ scenes { id title tags { id name } files { duration } } } }")["findScenes"]["scenes"]
    check(scenes, "Stash has scenes")
    scene = next((s for s in scenes if SENT_TAG not in {t["name"] for t in s["tags"]}), None)
    if scene is None:  # every scene was sent by an earlier run: recycle the first
        scene = scenes[0]
        stash.gql("mutation($ids: [ID!]!, $t: [ID!]) { bulkSceneUpdate(input: {ids: $ids, tag_ids: {ids: $t, mode: REMOVE}}) { id } }",
                  ids=[scene["id"]], t=[tags[SENT_TAG]])
    plugin.op("add_scenes", scene_ids=[scene["id"]])
    queue = plugin.op("queue")["items"]
    whole = next((c for c in queue if c["kind"] == "clip" and c.get("whole_scene") and c.get("stash_scene_id") == scene["id"]), None)
    check(whole is not None, f"queue shows the whole scene ({whole['id'] if whole else '-'}) spanning {whole['duration'] if whole else 0:.1f} s")
    check(not whole.get("stash_marker_id"), "it has no marker behind it")
    plugin.op("item_update", item_id=whole["id"], changes={"in_s": 0.0, "out_s": min(4.0, whole["duration"]), "cover_t": 2.0})
    for search in ("near", "from_in"):  # the seamless-loop finder runs through Stash's ffmpeg; it may find nothing in this footage
        found = plugin.op("loop_find", item_id=whole["id"], search=search)["candidates"]
        check(isinstance(found, list) and all(c["out_s"] - c["in_s"] >= 1.0 and c["quality"] for c in found),
              f"loop finder ({search}) answered with {len(found)} candidate(s)")
    unchanged = plugin.op("item_detail", item_id=whole["id"])["item"]
    check((unchanged["in_s"], unchanged["out_s"]) == (0.0, min(4.0, whole["duration"])), "the finder saved nothing")
    plugin.op("send", item_id=whole["id"], blog_id=blog["id"], action="draft")
    sent_scene = plugin.wait_sent(whole["id"])
    check(sent_scene["sent_as"] == "draft" and sent_scene["draft_id"], f"whole scene sent as draft {sent_scene['draft_id']}")
    check((sent_scene.get("output_note") or "").endswith("with cover"),
          f"it opens on the cover frame ({sent_scene.get('output_note')})")
    scene_tags = {t["name"] for t in stash.gql(
        "query($id: ID!) { findScene(id: $id) { tags { name } } }", id=scene["id"])["findScene"]["tags"]}
    check(SENT_TAG in scene_tags and QUEUE_TAG not in scene_tags, f"scene tags swapped to {SENT_TAG}")
    markers_after = stash.gql("{ findSceneMarkers(filter: {per_page: 1}) { count } }")["findSceneMarkers"]["count"]
    check(markers_after == len(markers), "no marker was created")
    browse_and_save(stash, plugin, blog)
    print("e2e: all checks passed")


def op_error(plugin, mode, **args):
    """The message an operation fails with (it must fail)."""
    try:
        plugin.op(mode, **args)
    except RuntimeError as e:
        return str(e)
    sys.exit(f"{mode} should have failed")


def browse_and_save(stash, plugin, blog):
    print("browse imaglr and save posts")
    setup = plugin.op("save_setup")
    check(setup["enabled"] and any(lib["path"] == "/saved" for lib in setup["libraries"]),
          "browsing is on and /saved is a library (dev/seed.py <port> saving)")
    check(plugin.op("save_folder_set", folder="/saved/imaglr")["folder_ok"], "save folder chosen inside /saved")
    # A clean start: whatever an earlier run saved goes, files and all, so the downloads happen again.
    found = stash.gql("""query($f: [CustomFieldCriterionInput!]) {
        findScenes(scene_filter: {custom_fields: $f}) { scenes { id } }
        findImages(image_filter: {custom_fields: $f}) { images { id } }
        findGalleries(gallery_filter: {custom_fields: $f}) { galleries { id } } }""",
                      f=[{"field": "imaglr_post_id", "modifier": "NOT_NULL", "value": []}])
    if found["findGalleries"]["galleries"]:
        stash.gql("mutation($ids: [ID!]!) { galleryDestroy(input: {ids: $ids}) }", ids=[g["id"] for g in found["findGalleries"]["galleries"]])
    if found["findImages"]["images"]:
        stash.gql("mutation($ids: [ID!]!) { imagesDestroy(input: {ids: $ids, delete_file: true, delete_generated: true}) }",
                  ids=[i["id"] for i in found["findImages"]["images"]])
    if found["findScenes"]["scenes"]:
        stash.gql("mutation($ids: [ID!]!) { scenesDestroy(input: {ids: $ids, delete_file: true, delete_generated: true}) }",
                  ids=[s["id"] for s in found["findScenes"]["scenes"]])

    feed = plugin.op("browse", source="feed")
    check(len(feed["posts"]) == 20 and feed["next"], "the feed's first page, with a link to the next")
    more = plugin.op("browse", source="feed", next=feed["next"])
    ids = [p["id"] for p in feed["posts"] + more["posts"]]
    check(len(ids) == len(set(ids)) == 26 and more["next"] is None, "the second page carries on to the end")
    creator = plugin.op("browse", source="creator", name="ocean-views")
    check(creator["profile"]["name"] == "ocean-views" and all(p["creator"]["name"] == "ocean-views" for p in creator["posts"]),
          "a creator's page")
    check([p["id"] for p in plugin.op("browse", source="tag", tag="Beach")["posts"]] == ["7000"], "a tag's page")
    check({p["id"] for p in plugin.op("browse", source="likes")["posts"]} == {"7000", "7002", "7003", "7010"}, "the likes")
    video = next(m["url"] for p in feed["posts"] + more["posts"] for m in p["media"] if m["kind"] == "video")
    src = plugin.op("media_preview", url=video)["src"]
    with urllib.request.urlopen(f"{stash.base}/{src}", timeout=30) as r:
        check(r.status == 200 and r.headers.get_content_type() == "video/mp4" and len(r.read()) > 1000,
              "a video plays from Stash's own address")
    check("isn't on imaglr" in op_error(plugin, "media_preview", url="https://elsewhere.example/a.mp4"), "other hosts refused")

    for post_id in ("7002", "7004"):  # three files; and a reblog of 7000, saved as 7000 by sunny-days
        plugin.op("save_post", post_id=post_id)
    deadline = time.time() + 240
    while time.time() < deadline:
        saves = {s["post_id"]: s for s in plugin.op("save_status")["saves"]}
        if all(saves.get(p, {}).get("status") in ("done", "failed") for p in ("7002", "7000")):
            break
        time.sleep(2)
    for post_id in ("7002", "7000"):
        save = saves.get(post_id) or {}
        check(save.get("status") == "done", f"post {post_id} saved ({save.get('status')} {save.get('error') or ''})".rstrip())
    image = stash.gql("""{ findImages(image_filter: {custom_fields: [{field: "imaglr_post_id", modifier: EQUALS, value: ["7000"]}]}) {
        images { title urls details custom_fields tags { name } performers { name } visual_files { ... on ImageFile { path } } } } }""")["findImages"]["images"]
    check(len(image) == 1, "the reblog was saved once, as the original post")
    image = image[0]
    check(image["urls"] == ["https://imaglr.example/post/7000", "https://imaglr.example/profile/sunny-days"], "credited with links")
    check(image["custom_fields"] == {"imaglr_post_id": "7000", "imaglr_creator": "sunny-days"}, "and custom fields")
    check(image["details"].startswith("Saved from imaglr. Posted by @sunny-days"), "and a credit line")
    check(image["visual_files"][0]["path"] == "/saved/imaglr/sunny-days/7000.png", "filed under the creator, named by post")
    check(sorted(t["name"] for t in image["tags"]) == ["Beach", "Sunset"], "imaglr tags matched Stash tags, never the queue tag")
    check([p["name"] for p in image["performers"]] == ["Test Performer"], "a tag matched a performer by full name")
    gallery = stash.gql("""{ findGalleries(gallery_filter: {custom_fields: [{field: "imaglr_post_id", modifier: EQUALS, value: ["7002"]}]}) {
        galleries { image_count scenes { id } studio { name } } } }""")["findGalleries"]["galleries"]
    check(len(gallery) == 1 and gallery[0]["image_count"] == 2 and len(gallery[0]["scenes"]) == 1
          and gallery[0]["studio"]["name"] == "Test Studio", "several files became one gallery")
    check(plugin.op("save_post", post_id="7000")["save"]["status"] == "done", "saving it again just points at it")
    liked = {p["id"]: p for p in plugin.op("browse", source="likes")["posts"]}
    check(liked["7000"]["saved"] and liked["7002"]["saved"], "the feed shows both as in the library")

    print("a saved post is reblogged, never uploaded again")
    image_id = stash.gql("""{ findImages(image_filter: {custom_fields: [{field: "imaglr_post_id", modifier: EQUALS, value: ["7000"]}]}) {
        images { id } } }""")["findImages"]["images"][0]["id"]
    added = plugin.op("add_images", image_ids=[image_id])
    item_id = (added.get("item_ids") or [None])[0] or next(c["id"] for c in plugin.op("queue")["items"] if c.get("stash_image_id") == image_id)
    card = next(c for c in plugin.op("queue")["items"] if c["id"] == item_id)
    check(card.get("saved_from") == "7000", "its card says it came from imaglr")
    check("Reblog" in op_error(plugin, "send", item_id=item_id, blog_id=blog["id"]), "sending it is refused")
    plan = plugin.op("send_all", item_ids=[item_id], dry_run=True)
    check(plan["plan"][0].get("skip") == "from_imaglr", "Send all skips it")
    check(plugin.op("reblog", post_id="7000", blog_id=blog["id"])["ok"], "reblogged instead")
    plugin.op("remove_from_queue", item_id=item_id)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "8900")
